"""Durable, bounded, model-directed lesson agent. RAG stays behind its own tool.

The controller is deliberately small: propose one action, validate, execute,
checkpoint, observe. A model cannot grant itself scope, approve relations or
declare a failed delivery check successful.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from backend.database import Chapter, Chunk, Job, SessionLocal, Textbook
from backend.agents.orchestrator import _write_with_retry
from backend.agents.lesson_contracts import DecisionValidationError, decision_fingerprint, validate_decision
from backend.agents.lesson_policy import DecisionUnavailable, decide_next_action
from backend.agents.rag_tool import query_rag_tool

VERSION = 'lesson_agent_v3'
TOOLS = ['inspect_course', 'query_rag', 'read_source', 'write_draft', 'validate_draft', 'ask_teacher', 'finish']
MAX_EVIDENCE = 48


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _limit(name: str, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def runtime_fields() -> dict:
    return {
        'execution_mode': 'model_driven', 'trajectory': [], 'teacher_answers': [],
        'available_tools': TOOLS[:], 'stop_reason': None,
        'budget': {
            'max_steps': _limit('AGENT_MAX_STEPS', 12, 4, 40), 'steps_used': 0,
            'max_rag_queries': _limit('AGENT_MAX_RAG_QUERIES', 6, 1, 15), 'rag_queries_used': 0,
            'max_drafts': _limit('AGENT_MAX_DRAFTS', 3, 1, 6), 'drafts_used': 0,
            'max_runtime_seconds': _limit('AGENT_MAX_RUNTIME_SECONDS', 300, 30, 900),
            'elapsed_seconds': 0,
        },
        'artifact_versions': [], 'no_progress_count': 0,
    }


class RunCancelled(RuntimeError):
    pass


def _load(job_id: str) -> tuple[dict, dict, str]:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.type != 'course_agent':
            raise ValueError('备课任务不存在')
        return copy.deepcopy(job.payload or {}), copy.deepcopy(job.result or {}), job.status


def _ensure_active(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status == 'cancelled':
            raise RunCancelled()


def save_checkpoint(job_id: str, state: dict, *, status: str = 'processing', stage: str = 'agent', message: str = '', error: str = '', progress: int | None = None) -> None:
    # An atomic predicate protects a concurrent user cancellation from late tool results.
    def save(db):
        values = {'result': copy.deepcopy(state), 'status': status, 'stage': stage,
                  'message': message, 'error': error, 'updated_at': datetime.now(timezone.utc)}
        values['progress'] = progress if progress is not None else 100 if status in {'completed', 'cancelled'} else 0
        values['total'] = 100
        changed = db.query(Job).filter(Job.id == job_id, Job.type == 'course_agent', Job.status != 'cancelled').update(values, synchronize_session=False)
        if not changed:
            raise RunCancelled()
    _write_with_retry(save)


def _books(payload: dict) -> list:
    from backend.agents.course_agent import _selected_books
    return _selected_books(payload.get('course_id') or 'course_default', payload['textbook_ids'])


def _snapshot(chunk, title: str, chapter_title: str) -> dict:
    text = chunk.content or ''
    return {
        'id': chunk.id, 'textbook_id': chunk.textbook_id, 'textbook': title,
        'chapter_id': chunk.chapter_id, 'chapter': chapter_title,
        'section_path': chunk.section_path or [], 'page_start': chunk.page_start,
        'page_end': chunk.page_end, 'content': text[:12000],
        'source_hash': hashlib.sha256(text.encode()).hexdigest(),
        'source_truncated': len(text) > 12000,
    }


def _read_sources(payload: dict, chunk_ids: list[str]) -> list[dict]:
    if len(chunk_ids) > MAX_EVIDENCE:
        raise ValueError('最多保留48段原文')
    with SessionLocal() as db:
        rows = db.query(Chunk, Textbook.title, Chapter.title).join(Textbook, Chunk.textbook_id == Textbook.id).join(
            Chapter, Chunk.chapter_id == Chapter.id,
        ).filter(
            Textbook.course_id == (payload.get('course_id') or 'course_default'),
            Textbook.id.in_(payload['textbook_ids']), Chapter.textbook_id == Textbook.id, Chunk.id.in_(chunk_ids),
        ).all()
        if any(not (chunk.content or '').strip() for chunk, _, _ in rows):
            raise ValueError('所选原文为空，不能作为教材支持证据')
        by_id = {chunk.id: _snapshot(chunk, title, chapter_title) for chunk, title, chapter_title in rows}
        if set(by_id) != set(chunk_ids):
            raise ValueError('原文不存在或已超出本次教材范围')
        return [by_id[value] for value in chunk_ids]


def _evidence_current(payload: dict, evidence: list[dict]) -> bool:
    if not evidence:
        return True
    try:
        current = _read_sources(payload, [item['id'] for item in evidence])
    except (KeyError, ValueError):
        return False
    return all(
        all(a.get(key) == b.get(key) for key in ('id', 'textbook_id', 'textbook', 'chapter_id', 'chapter', 'section_path', 'page_start', 'page_end', 'source_hash'))
        for a, b in zip(current, evidence)
    )


def _add_evidence(payload: dict, state: dict, chunk_ids: list[str]) -> int:
    existing = {item['id'] for item in state.get('evidence') or []}
    new_ids = list(dict.fromkeys(value for value in chunk_ids if value not in existing))
    remaining = max(0, MAX_EVIDENCE - len(existing))
    additions = _read_sources(payload, new_ids[:remaining])
    if additions:
        state.setdefault('evidence', []).extend(additions)
        state.pop('validated_signature', None)
    return len(additions)


def _signature(state: dict) -> str:
    value = {'evidence': [(item.get('id'), item.get('source_hash')) for item in state.get('evidence') or []],
             'artifact': state.get('lesson_draft') or state.get('artifact')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _observation(state: dict, value: dict) -> None:
    state.setdefault('observations', {})['last_tool_result'] = value


def _stale_sources(state: dict) -> None:
    state.pop('validated_signature', None)
    state['quality'] = None
    state['delivery'] = {'status': 'needs_work', 'missing_items': ['教材原文已经变化，请基于新来源创建任务'],
                         'checks': [], 'semantic_reviewed': False}


def _validate(payload: dict, state: dict) -> dict:
    from backend.agents.course_agent import verify_artifact
    artifact = state.get('lesson_draft') or state.get('artifact')
    if not artifact:
        raise ValueError('尚未生成可检查的教案')
    if not _evidence_current(payload, state.get('evidence') or []):
        _stale_sources(state)
        raise ValueError('原文已经变化，请基于新来源创建任务；已保存稿保持不变')
    quality = verify_artifact(artifact, payload['textbook_ids'], payload)
    state['quality'] = quality
    state['delivery'] = quality['task_completion']
    state['validated_signature'] = _signature(state)
    return {'summary': '已检查来源与交付结构，教学正确性仍需教师核对',
            'delivery': state['delivery']['status'], 'missing_items': state['delivery']['missing_items'],
            'semantic_reviewed': False}


def _partial(payload: dict, state: dict, reason: str, message: str) -> None:
    from backend.agents.course_agent import _fallback_artifact, _citations, verify_artifact
    if not state.get('artifact') and state.get('evidence'):
        state['artifact'] = _fallback_artifact(payload['topic'], state['evidence'], _citations(state['evidence']), message)
    if not _evidence_current(payload, state.get('evidence') or []):
        _stale_sources(state)
    elif state.get('artifact') or state.get('lesson_draft'):
        # Even an exhausted run preserves a valid draft; the stop reason is separate.
        quality = verify_artifact(state.get('lesson_draft') or state['artifact'], payload['textbook_ids'], payload)
        state['quality'] = quality
        state['delivery'] = quality['task_completion']
    else:
        state['delivery'] = {'status': 'needs_work', 'missing_items': [message], 'checks': [], 'semantic_reviewed': False}
    state['stop_reason'] = reason
    state['completed_at'] = now()


def _prepare_environment(job_id: str, payload: dict, state: dict, checkpoint: Callable | None = None) -> bool:
    from backend.agents.course_agent import _book_observation
    books = _books(payload)
    missing = [book for book in books if book.parse_status in {'pending', 'failed'}]
    if missing:
        from backend.agents.ingestion_agent import ingest_textbook, chunk_textbook
        for book in missing:
            _ensure_active(job_id)
            ingest_textbook(book.id, force=False)
            chunk_textbook(book.id)
        books = _books(payload)
    state.setdefault('observations', {})['textbooks'] = [_book_observation(book) for book in books]
    awaiting = [book for book in books if book.structure_status not in {'confirmed', 'legacy_confirmed'}]
    if awaiting:
        state['approval'] = {'type': 'chapter_review', 'title': '确认章节结构后继续',
                             'message': '确认原文定位后，Agent 会根据工具结果决定下一步。',
                             'textbooks': [{'id': book.id, 'title': book.title} for book in awaiting]}
        if checkpoint:
            checkpoint(status='waiting_user', stage='approval', message='等待教师确认章节结构')
        else:
            save_checkpoint(job_id, state, status='waiting_user', stage='approval', message='等待教师确认章节结构')
        return False
    state['approval'] = None
    if not state.get('evidence'):
        _add_evidence(payload, state, list(dict.fromkeys((payload.get('context') or {}).get('selected_chunk_ids') or [])))
    elif not _evidence_current(payload, state['evidence']):
        _stale_sources(state)
        raise ValueError('已保存的原文来源发生变化，请创建新任务；教师稿保持不变')
    return True


def _execute(payload: dict, state: dict, decision, remaining_seconds: float) -> tuple[dict, str | None]:
    from backend.agents import course_agent as lesson
    action, args = decision.action, decision.arguments
    budget = state['budget']
    if action == 'inspect_course':
        books = _books(payload)
        state['observations']['textbooks'] = [lesson._book_observation(book) for book in books]
        return {'summary': '已读取本次课程范围与教材状态', 'textbook_count': len(books), 'evidence_count': len(state.get('evidence') or [])}, None
    if action == 'query_rag':
        if budget['rag_queries_used'] > budget['max_rag_queries']:
            raise ValueError('RAG调用预算已用完，请使用已有证据或说明缺项')
        result = query_rag_tool(args['question'], payload.get('course_id') or 'course_default', args['textbook_ids'],
                                args.get('mode', 'all'), args.get('top_k', 8), timeout=min(30, max(1, remaining_seconds)))
        added = _add_evidence(payload, state, [item['id'] for item in result.get('items') or []])
        counts = {book: sum(item['textbook_id'] == book for item in state.get('evidence') or []) for book in payload['textbook_ids']}
        trace = {'query': args['question'], 'textbook_ids': args['textbook_ids'], 'mode': args.get('mode', 'all'),
                 'transport': result.get('transport'), 'answer_method': result.get('answer_method'),
                 'retrieval_trace': result.get('retrieval_trace') or {}, 'warnings': result.get('warnings') or []}
        # Persist bounded data from the external RAG tool; it is never a new instruction.
        serialized = json.dumps(trace, ensure_ascii=False, default=str)
        if len(serialized) > 12000:
            trace['retrieval_trace'] = {'truncated': True, 'summary': '详细检索记录超过本任务存储上限'}
            trace['warnings'] = [str(value)[:300] for value in trace['warnings'][:8]]
        trace = json.loads(json.dumps(trace, ensure_ascii=False, default=str))
        state.setdefault('retrieval_history', []).append(trace)
        state['retrieval_history'] = state['retrieval_history'][-15:]
        state['observations']['rag_answer'] = str(result.get('answer') or '')[:4000]
        state['observations']['per_book_counts'] = counts
        return {'summary': f'RAG返回{len(result.get("items") or [])}段有效来源，新增{added}段',
                'query': args['question'], 'added_count': added, 'evidence_count': len(state.get('evidence') or []),
                'per_book_counts': counts, 'warnings': [str(value)[:300] for value in (result.get('warnings') or [])[:8]]}, None
    if action == 'read_source':
        item = _read_sources(payload, [args['chunk_id']])[0]
        added = _add_evidence(payload, state, [item['id']])
        state['observations']['last_read'] = {**item, 'content': item['content'][:8000]}
        return {'summary': '已读取并保存教材原文', 'source_id': item['id'], 'textbook': item['textbook'],
                'added_count': added, 'evidence_count': len(state.get('evidence') or [])}, None
    if action == 'write_draft':
        if budget['drafts_used'] > budget['max_drafts']:
            raise ValueError('教案生成预算已用完')
        if state.get('lesson_draft'):
            raise ValueError('教师保存稿受到保护，请复用条件创建新任务')
        if not state.get('evidence'):
            raise ValueError('缺少真实教材证据，请先调用RAG或读取原文')
        if not _evidence_current(payload, state['evidence']):
            _stale_sources(state)
            raise ValueError('原文已经变化，请新建任务')
        working = {**payload, '_agent_runtime': True, '_agent_instructions': args.get('instructions', ''),
                   '_agent_feedback': state.get('delivery'), '_agent_previous_draft': state.get('artifact'),
                   '_agent_teacher_answers': state.get('teacher_answers') or [],
                   '_agent_timeout': min(60, max(1, remaining_seconds))}
        artifact = lesson._generate_artifact(working, _books(payload), state['evidence'])
        if state.get('artifact'):
            state['artifact_versions'] = (state.get('artifact_versions') or [])[-2:] + [{'artifact': state['artifact'], 'saved_at': now()}]
        state['artifact'] = artifact
        state.pop('validated_signature', None)
        # Do not reuse an earlier check after replacing its draft.
        state['quality'] = None
        state['delivery'] = None
        return {'summary': '已根据当前证据和检查反馈更新教案草稿', 'generation_method': artifact.get('generation_method'),
                'source_count': len(artifact.get('citations') or []), 'draft_version': budget['drafts_used']}, None
    if action == 'validate_draft':
        return _validate(payload, state), None
    if action == 'ask_teacher':
        if len(state.get('teacher_answers') or []) >= 4:
            raise ValueError('已达到教师补充次数上限，请保留缺项并结束本次尝试')
        state['approval'] = {'type': 'teacher_question', 'title': 'Agent 需要补充备课条件',
                             'message': '回答后会从当前证据和教案继续，不重新开始。',
                             'question': args['question'], 'options': args.get('options') or [],
                             'request_id': 'question_' + uuid.uuid4().hex[:16]}
        return {'summary': '已保存检查点，等待教师补充', 'question': args['question']}, 'waiting_user'
    if action == 'finish':
        observation = _validate(payload, state)
        if state['delivery']['status'] != 'draft_ready':
            raise ValueError('交付检查未通过，请按missing_items补充证据、修订草稿或询问教师')
        state['stop_reason'] = 'delivery_ready'
        state['completed_at'] = now()
        return {**observation, 'summary': '交付结构与来源检查通过，教案等待教师审核'}, 'completed'
    raise ValueError('不支持的工具')


def process_agent_loop(job_id: str, *, policy: Callable | None = None) -> None:
    payload, state, status = _load(job_id)
    if status in {'cancelled', 'completed', 'waiting_user'}:
        return
    defaults = runtime_fields()
    for key, value in defaults.items():
        state.setdefault(key, copy.deepcopy(value))
    state['agent_version'] = VERSION
    state['execution_mode'] = 'model_driven'
    state['stop_reason'] = None
    state.setdefault('evidence', [])
    state.setdefault('plan', [])
    state.setdefault('observations', {})
    budget = state['budget']
    for key, value in defaults['budget'].items():
        budget.setdefault(key, value)
    base_elapsed = float(budget.get('elapsed_seconds') or 0)
    started = time.monotonic()
    chooser = policy or decide_next_action

    def checkpoint(**kwargs):
        budget['elapsed_seconds'] = round(base_elapsed + time.monotonic() - started, 3)
        save_checkpoint(job_id, state, **kwargs)

    def stop(reason: str, message: str):
        _partial(payload, state, reason, message)
        checkpoint(status='completed', stage='stopped', message=message)

    try:
        _ensure_active(job_id)
        # Completed actions are not replayed. An interrupted proposal/tool spent its
        # reserved budget and is presented as an observation to the next decision.
        for entry in state['trajectory']:
            if entry.get('status') == 'running':
                entry.update(status='failed', error='interrupted', finished_at=now(),
                             observation={'summary': '上次动作被中断，将依据已保存状态重新决策'})
                for row in state['plan']:
                    if row.get('id') == entry['id']:
                        row.update(status='failed', message='上次动作被中断，已恢复检查点')
        checkpoint(stage='inspect', message='正在恢复任务状态并检查教材范围')
        if not _prepare_environment(job_id, payload, state, checkpoint):
            return
        while budget['steps_used'] < budget['max_steps']:
            _ensure_active(job_id)
            remaining = budget['max_runtime_seconds'] - (base_elapsed + time.monotonic() - started)
            if remaining <= 0:
                stop('time_budget', '已达到调度时限，保留当前成果与未完成项')
                return
            budget['steps_used'] += 1
            checkpoint(stage='planning', message='Agent 正在根据工具结果选择下一步')
            entry = {'id': 'action_' + uuid.uuid4().hex[:16], 'step': budget['steps_used'],
                     'action': 'invalid_action', 'summary': '检查模型动作', 'status': 'running', 'started_at': now()}
            before = _signature(state)
            try:
                raw = chooser(payload, state, timeout=min(45, max(1, remaining)))
                decision = validate_decision(raw.model_dump() if hasattr(raw, 'model_dump') else raw, payload)
                entry.update(action=decision.action, summary=decision.summary, arguments=decision.arguments)
                _ensure_active(job_id)
                remaining = budget['max_runtime_seconds'] - (base_elapsed + time.monotonic() - started)
                if remaining <= 0:
                    stop('time_budget', '已达到调度时限，保留当前成果与未完成项')
                    return
                fingerprint = decision_fingerprint(decision)
                prior_same = sum(row.get('fingerprint') == fingerprint and row.get('input_signature') == before for row in state['trajectory'])
                entry.update(fingerprint=fingerprint, input_signature=before)
                if prior_same >= 2:
                    raise ValueError('重复动作没有取得新进展，请改变查询或说明缺项')
                if decision.action == 'query_rag':
                    if budget['rag_queries_used'] >= budget['max_rag_queries']:
                        raise ValueError('RAG调用预算已用完')
                    budget['rag_queries_used'] += 1
                if decision.action == 'write_draft':
                    if budget['drafts_used'] >= budget['max_drafts']:
                        raise ValueError('教案生成预算已用完')
                    budget['drafts_used'] += 1
                state['trajectory'].append(entry)
                state['plan'].append({'id': entry['id'], 'title': decision.summary, 'tool': decision.action, 'status': 'running'})
                checkpoint(stage=decision.action, message=decision.summary)
                remaining = budget['max_runtime_seconds'] - (base_elapsed + time.monotonic() - started)
                if remaining <= 0:
                    entry.update(status='failed', error='time_budget', finished_at=now())
                    state['plan'][-1].update(status='failed', message='已达到调度时限，未启动工具')
                    stop('time_budget', '已达到调度时限，保留当前成果与未完成项')
                    return
                observation, terminal = _execute(payload, state, decision, remaining)
                _ensure_active(job_id)
                entry.update(status='completed', finished_at=now(), observation=observation)
                _observation(state, observation)
                state['plan'][-1].update(status='completed', message=observation['summary'])
                if decision.action not in state.setdefault('tools_used', []):
                    state['tools_used'].append(decision.action)
                progressed = before != _signature(state) or decision.action in {'read_source', 'validate_draft', 'inspect_course'}
                state['no_progress_count'] = 0 if progressed else state.get('no_progress_count', 0) + 1
                if terminal == 'waiting_user':
                    checkpoint(status='waiting_user', stage='approval', message='等待教师补充备课条件')
                    return
                if terminal == 'completed':
                    checkpoint(status='completed', stage='completed', message='教案交付检查通过，等待教师审核')
                    return
                checkpoint(stage='observe', message=observation['summary'])
            except DecisionUnavailable as exc:
                entry.update(status='failed', action='model_decision', summary='模型决策暂不可用', error=getattr(exc, 'code', 'model_error'), finished_at=now())
                if entry not in state['trajectory']:
                    state['trajectory'].append(entry)
                _partial(payload, state, 'decision_unavailable', '模型决策不可用，已保留当前证据和稿件')
                checkpoint(status='failed', stage='failed', message='模型决策不可用，可稍后重试', error=getattr(exc, 'code', 'model_error'))
                return
            except (DecisionValidationError, ValueError, TypeError, KeyError) as exc:
                if entry not in state['trajectory']:
                    state['trajectory'].append(entry)
                failure = {'summary': str(exc)[:300] if isinstance(exc, ValueError) else '动作参数或返回结构未通过检查'}
                if isinstance(exc, DecisionValidationError):
                    failure.update(error_code=exc.code, validation_issues=exc.issues,
                                   correction='只返回 action、arguments、summary；按白名单动作的参数格式修正，不能输出教案代替动作。',
                                   allowed_actions=TOOLS[:])
                error = failure['summary']
                entry.update(status='rejected', finished_at=now(), error=error, observation=failure)
                if state['plan'] and state['plan'][-1]['id'] == entry['id']:
                    state['plan'][-1].update(status='failed', message=error)
                _observation(state, {**failure, 'rejected_action': entry['action']})
                state['no_progress_count'] = state.get('no_progress_count', 0) + 1
                checkpoint(stage='observe', message='已拒绝不可执行动作，Agent 将依据反馈调整')
            if state.get('no_progress_count', 0) >= 4:
                stop('no_progress', '多轮操作未取得进展，已保留证据、草稿和未完成项')
                return
        stop('step_budget', '已达到动作轮数上限，保留当前成果与未完成项')
    except RunCancelled:
        return
    except Exception as exc:
        state['stop_reason'] = 'runtime_error'
        try:
            checkpoint(status='failed', stage='failed', message='Agent 执行中断，已保留检查点', error=type(exc).__name__)
        except RunCancelled:
            pass
