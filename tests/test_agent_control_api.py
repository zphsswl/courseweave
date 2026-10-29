"""Teacher checkpoints and cancellation against real database transactions."""
import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
with patch('dotenv.load_dotenv', return_value=False):
    from backend.api import agent as api
    from backend.agents import orchestrator, lesson_runtime
    from backend.database import Base, Course, Job, Textbook

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class AgentControlApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.stack = ExitStack()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.stack.close)
        for module in (api, orchestrator, lesson_runtime):
            self.stack.enter_context(patch.object(module, 'SessionLocal', self.sessions))
        self.queue = self.stack.enter_context(patch.object(api, 'enqueue_job'))
        with self.sessions() as db:
            db.add(Course(id='control', title='控制接口'))
            db.flush()
            db.add(Textbook(id='control_book', course_id='control', title='教材', filename='book.txt', format='txt', structure_status='confirmed'))
            db.flush()
            db.add(Job(id='control_run', course_id='control', type='course_agent', status='waiting_user',
                       payload={'course_id': 'control', 'textbook_ids': ['control_book']},
                       result={'agent_version': 'lesson_agent_v3', 'draft_revision': 3,
                               'artifact': {'title': '现有草稿'}, 'lesson_draft': {'title': '教师保存稿'},
                               'evidence': [{'id': 'source'}], 'teacher_answers': [],
                               'approval': {'type': 'teacher_question', 'request_id': 'question_one', 'question': '课堂更侧重哪个环节？'}}))
            db.commit()

    def change(self, *, status=None, **state):
        with self.sessions() as db:
            row = db.get(Job, 'control_run')
            if status:
                row.status = status
            row.result = {**row.result, **state}
            db.commit()

    def saved(self):
        return api.get_agent_run('control_run')

    def answer(self, answer='  多安排讨论  ', request_id='question_one'):
        return api.respond_to_agent('control_run', api.AgentTeacherResponse(request_id=request_id, answer=answer))

    def test_answer_checkpoints_exact_question_preserves_work_and_enqueues_once(self):
        result = self.answer()
        self.assertEqual(result['status'], 'pending')
        state = result['result']
        self.assertIsNone(state['approval'])
        self.assertEqual(state['teacher_answers'][0]['answer'], '多安排讨论')
        self.assertEqual(state['teacher_answers'][0]['question'], '课堂更侧重哪个环节？')
        self.assertEqual(state['lesson_draft']['title'], '教师保存稿')
        self.assertEqual(state['draft_revision'], 3)
        self.queue.assert_called_once_with('control_run')
        with self.assertRaises(HTTPException) as error:
            self.answer()
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.saved()['result']['teacher_answers']), 1)
        self.queue.assert_called_once()

    def test_stale_question_blank_answer_and_excess_answers_do_not_enqueue(self):
        for arguments, expected in [({'request_id': 'old_question'}, 409), ({'answer': ' \n '}, 422)]:
            with self.subTest(arguments=arguments), self.assertRaises(HTTPException) as error:
                self.answer(**arguments)
            self.assertEqual(error.exception.status_code, expected)
        self.change(teacher_answers=[{'answer': str(index)} for index in range(4)])
        with self.assertRaises(HTTPException) as error:
            self.answer()
        self.assertEqual(error.exception.status_code, 409)
        self.queue.assert_not_called()

    def test_answer_schema_bounds_text_before_execution(self):
        for answer in ('', '字' * 2001):
            with self.assertRaises(ValidationError):
                api.AgentTeacherResponse(request_id='question_one', answer=answer)

    def test_resume_cannot_bypass_teacher_question(self):
        with self.assertRaises(HTTPException) as error:
            api.resume_agent_run('control_run')
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.saved()['status'], 'waiting_user')
        self.queue.assert_not_called()

    def test_chapter_resume_handles_null_legacy_approval(self):
        self.change(approval=None)
        self.assertEqual(api.resume_agent_run('control_run')['status'], 'pending')
        self.queue.assert_called_once_with('control_run')

    def test_cancel_is_idempotent_and_preserves_sources_and_teacher_work(self):
        previous = copy.deepcopy(self.saved()['result'])
        result = api.cancel_agent_run('control_run')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['result']['stop_reason'], 'user_cancelled')
        for key in ('evidence', 'lesson_draft', 'artifact', 'draft_revision'):
            self.assertEqual(result['result'][key], previous[key])
        self.assertEqual(api.cancel_agent_run('control_run')['status'], 'cancelled')
        self.queue.assert_not_called()

    def test_cancelled_run_rejects_late_answer_resume_and_checkpoint(self):
        api.cancel_agent_run('control_run')
        for operation in (self.answer, lambda: api.resume_agent_run('control_run')):
            with self.assertRaises(HTTPException) as error:
                operation()
            self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(lesson_runtime.RunCancelled):
            lesson_runtime.save_checkpoint('control_run', {'artifact': {'title': '迟到结果'}}, status='completed')
        self.assertEqual(self.saved()['result']['lesson_draft']['title'], '教师保存稿')

    def test_terminal_and_historical_runs_cannot_be_cancelled(self):
        for status in ('completed', 'failed'):
            self.change(status=status)
            with self.assertRaises(HTTPException) as error:
                api.cancel_agent_run('control_run')
            self.assertEqual(error.exception.status_code, 409)
        self.change(status='pending', agent_version='lesson_agent_v2')
        with self.assertRaises(HTTPException) as error:
            api.cancel_agent_run('control_run')
        self.assertEqual(error.exception.status_code, 409)

    def test_control_routes_reject_missing_or_other_job_types(self):
        with self.sessions() as db:
            row = db.get(Job, 'control_run')
            row.type = 'parse'
            db.commit()
        for identifier in ('control_run', 'missing'):
            for operation in (api.cancel_agent_run, api.resume_agent_run,
                              lambda value: api.respond_to_agent(value, api.AgentTeacherResponse(request_id='question_one', answer='回答'))):
                with self.subTest(identifier=identifier, operation=operation), self.assertRaises(HTTPException) as error:
                    operation(identifier)
                self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
