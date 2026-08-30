"""Rebuild all textbook-derived data with verified evidence and full alignment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(stage: str, **payload) -> None:
    print(json.dumps({"stage": stage, **payload}, ensure_ascii=False), flush=True)


def rebuild(textbook_ids: list[str], skip_alignment: bool = False) -> None:
    from backend.agents.ingestion_agent import ingest_textbook, chunk_textbook
    from backend.agents.kg_extraction_agent import extract_textbook_graph
    from backend.agents.rag_agent import build_rag_index
    from backend.database import Chapter, SessionLocal, Textbook
    from backend.services.alignment_service import run_alignment

    started = time.time()
    for index, textbook_id in enumerate(textbook_ids, start=1):
        emit("parse_started", textbook_id=textbook_id, current=index, total=len(textbook_ids))
        parse_result = ingest_textbook(textbook_id, force=True)
        db = SessionLocal()
        try:
            book = db.query(Textbook).filter(Textbook.id == textbook_id).one()
            chapters = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).all()
            if not chapters:
                raise RuntimeError(f"{textbook_id} 没有识别到可用章节")
            book.structure_status = "confirmed"
            for chapter in chapters:
                chapter.review_status = "confirmed"
            db.commit()
        finally:
            db.close()
        chunk_count = chunk_textbook(textbook_id)
        emit(
            "parse_completed",
            textbook_id=textbook_id,
            chapters=parse_result.get("chapters", 0),
            chunks=chunk_count,
        )

        graph_result = extract_textbook_graph(
            textbook_id,
            force=True,
            progress_callback=lambda progress, total, message, tid=textbook_id: emit(
                "graph_progress",
                textbook_id=tid,
                progress=progress,
                total=total,
                message=message,
            ),
        )
        if graph_result.get("error"):
            raise RuntimeError(f"{textbook_id}: {graph_result['error']}")
        emit("graph_completed", **graph_result)

    if not skip_alignment:
        emit("alignment_started", textbooks=len(textbook_ids), mode="full")
        alignment = run_alignment(textbook_ids=textbook_ids, judge_limit=None)
        emit("alignment_completed", **alignment)

    emit("rag_started")
    rag = build_rag_index()
    emit("rag_completed", **rag)
    emit("completed", seconds=round(time.time() - started, 1))


def rebuild_alignment(textbook_ids: list[str]) -> None:
    from backend.services.alignment_service import run_alignment

    started = time.time()
    emit("alignment_started", textbooks=len(textbook_ids), mode="full")
    alignment = run_alignment(textbook_ids=textbook_ids, judge_limit=None)
    emit("alignment_completed", **alignment)
    emit("completed", seconds=round(time.time() - started, 1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--textbooks", nargs="*", default=[])
    parser.add_argument("--skip-alignment", action="store_true")
    parser.add_argument(
        "--alignment-only",
        action="store_true",
        help="Refresh all cross-textbook candidates without reparsing textbooks.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Do not send textbook excerpts to an external model.",
    )
    args = parser.parse_args()

    if args.local_only:
        # python-dotenv does not override a deliberately supplied empty value.
        # This guarantees that every extractor and aligner stays local.
        os.environ["LLM_API_KEY"] = ""

    if args.textbooks:
        textbook_ids = list(dict.fromkeys(args.textbooks))
    else:
        from backend.database import SessionLocal, Textbook
        db = SessionLocal()
        try:
            textbook_ids = [row[0] for row in db.query(Textbook.id).order_by(Textbook.created_at).all()]
        finally:
            db.close()
    if len(textbook_ids) < 2 and not args.skip_alignment:
        raise RuntimeError("至少需要两本教材才能完成课程重建")
    if args.alignment_only:
        rebuild_alignment(textbook_ids)
    else:
        rebuild(textbook_ids, skip_alignment=args.skip_alignment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
