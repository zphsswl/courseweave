from sqlalchemy import (
    create_engine,
    event,
    inspect,
    text,
    Column,
    String,
    Integer,
    Float,
    Text,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime
from backend.config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_memory_sqlite = DATABASE_URL in {"sqlite:///:memory:", "sqlite://"}
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    poolclass=StaticPool if _is_memory_sqlite else None,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """Enable safe concurrency and relational integrity for local SQLite."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
Base = declarative_base()

DEFAULT_COURSE_ID = "course_default"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_legacy_columns()
    _bootstrap_default_course()
    _recover_interrupted_jobs()

# ── Models ──

class Course(Base):
    __tablename__ = "courses"
    id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=False, default="demo_user", index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    subject = Column(String, default="")
    status = Column(String, default="draft", index=True)  # draft | processing | review | published | archived
    default_granularity = Column(String, default="core")  # outline | core | detailed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Textbook(Base):
    __tablename__ = "textbooks"
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, default="")
    title = Column(String, nullable=False)
    format = Column(String, nullable=False)  # pdf, md, txt
    file_size = Column(Integer, default=0)
    total_pages = Column(Integer, default=0)
    total_chars = Column(Integer, default=0)
    parse_status = Column(String, default="pending")  # pending, processing, completed, failed
    graph_status = Column(String, default="pending")
    index_status = Column(String, default="pending")
    structure_status = Column(String, default="pending")  # pending | review | confirmed
    parse_warnings = Column(JSON, default=list)
    content_hash = Column(String, default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Chapter(Base):
    __tablename__ = "chapters"
    id = Column(String, primary_key=True)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False)
    title = Column(String, nullable=False)
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    content = Column(Text, default="")
    char_count = Column(Integer, default=0)
    parent_id = Column(String, default="")
    order_index = Column(Integer, default=0)
    level = Column(Integer, default=1)
    review_status = Column(String, default="unreviewed")
    extraction_status = Column(String, default="pending")  # pending | processing | completed
    source_spans = Column(JSON, default=list)

class TextbookPage(Base):
    __tablename__ = "textbook_pages"
    __table_args__ = (
        UniqueConstraint("textbook_id", "page_number", name="uq_textbook_page_number"),
    )
    id = Column(String, primary_key=True)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False, index=True)
    printed_page_number = Column(String, default="")
    text = Column(Text, default="")
    char_count = Column(Integer, default=0)
    content_hash = Column(String, default="", index=True)
    has_text = Column(Boolean, default=True)
    extraction_method = Column(String, default="native")  # native | pypdf | ocr | text
    created_at = Column(DateTime, default=datetime.utcnow)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(String, primary_key=True)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False)
    textbook_title = Column(String, default="")
    chapter_title = Column(String, default="")
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    content = Column(Text, default="")
    char_count = Column(Integer, default=0)
    chunk_index = Column(Integer, default=0)
    section_path = Column(JSON, default=list)
    content_hash = Column(String, default="", index=True)

class CanonicalConcept(Base):
    """Course-level concept that links source-specific KnowledgeNode occurrences."""
    __tablename__ = "canonical_concepts"
    __table_args__ = (
        UniqueConstraint("course_id", "canonical_name", name="uq_canonical_concept_course_name"),
    )
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False, index=True)
    canonical_name = Column(String, nullable=False, index=True)
    aliases = Column(JSON, default=list)
    concept_type = Column(String, default="concept")
    definition_summary = Column(Text, default="")
    status = Column(String, default="draft", index=True)  # draft | review | published | rejected
    teacher_locked = Column(Boolean, default=False)
    created_by = Column(String, default="alignment_agent")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=True, index=True)
    canonical_concept_id = Column(String, ForeignKey("canonical_concepts.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    aliases = Column(JSON, default=list)
    definition = Column(Text, default="")
    category = Column(String, default="")
    importance = Column(Integer, default=3)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False)
    textbook_title = Column(String, default="")
    chapter_title = Column(String, default="")
    page = Column(Integer, default=0)
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    source_chunk_id = Column(String, default="")
    source_paragraph = Column(Text, default="")
    source_sentences = Column(JSON, default=list)
    is_merged = Column(Boolean, default=False)
    merged_from = Column(JSON, default=list)
    teacher_locked = Column(Boolean, default=False)
    # Quality & granularity fields
    quality_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.5)
    granularity = Column(String, default="core_concept")
    learning_objective = Column(Text, default="")
    quality_flags = Column(JSON, default=list)
    # Essence fields
    is_essence = Column(Boolean, default=False)
    essence_score = Column(Float, default=0.0)
    essence_reason = Column(Text, default="")
    # Layered graph fields
    parent_id = Column(String, default="")
    section_title = Column(String, default="")
    display_level = Column(String, default="normal")  # overview | normal | detail
    node_role = Column(String, default="concept")  # textbook | chapter | section | concept | fact
    created_by = Column(String, default="")
    source_type = Column(String, default="llm")  # llm | rule | teacher | demo_seed
    review_status = Column(String, default="unreviewed", index=True)
    evidence_status = Column(String, default="unverified")  # unverified | verified | missing | invalid
    model_version = Column(String, default="")
    prompt_version = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=True, index=True)
    source = Column(String, nullable=False)
    target = Column(String, nullable=False)
    relation_type = Column(String, nullable=False)
    description = Column(String, default="")
    confidence = Column(Float, default=0.5)
    source_quote = Column(Text, default="")
    source_chunk_id = Column(String, default="")
    evidence = Column(JSON, default=list)
    created_by = Column(String, default="kg_extraction_agent")
    relation_subtype = Column(String, default="")
    direction_reason = Column(Text, default="")
    is_cross_textbook = Column(Boolean, default=False)
    review_status = Column(String, default="unreviewed", index=True)
    model_version = Column(String, default="")
    prompt_version = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class RelationEvidence(Base):
    __tablename__ = "relation_evidence"
    id = Column(String, primary_key=True)
    edge_id = Column(String, ForeignKey("knowledge_edges.id"), nullable=False, index=True)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False, index=True)
    chunk_id = Column(String, ForeignKey("chunks.id"), nullable=True, index=True)
    page_number = Column(Integer, default=0)
    source_quote = Column(Text, nullable=False)
    evidence_role = Column(String, default="supports")  # source | target | supports | contradicts
    quote_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AlignmentCandidate(Base):
    __tablename__ = "alignment_candidates"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", name="uq_alignment_candidate_pair"),
    )
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False, index=True)
    source_node_id = Column(String, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    target_node_id = Column(String, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    proposed_relation = Column(String, default="related_to")
    confidence = Column(Float, default=0.0, index=True)
    name_similarity = Column(Float, default=0.0)
    definition_similarity = Column(Float, default=0.0)
    context_similarity = Column(Float, default=0.0)
    reason = Column(Text, default="")
    differences = Column(Text, default="")
    evidence = Column(JSON, default=list)
    status = Column(String, default="pending", index=True)  # pending | approved | rejected | edited
    reviewed_by = Column(String, default="")
    reviewed_at = Column(DateTime, nullable=True)
    model_version = Column(String, default="")
    prompt_version = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class ReviewEvent(Base):
    __tablename__ = "review_events"
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False, index=True)
    target_type = Column(String, nullable=False)  # node | edge | alignment | chapter
    target_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # approve | reject | edit | merge | split | lock
    before = Column(JSON, default=dict)
    after = Column(JSON, default=dict)
    reason = Column(Text, default="")
    actor_id = Column(String, default="demo_user")
    created_at = Column(DateTime, default=datetime.utcnow)

class IntegrationDecision(Base):
    __tablename__ = "integration_decisions"
    id = Column(String, primary_key=True)
    action = Column(String, nullable=False)  # merge, keep, remove, split
    affected_nodes = Column(JSON, default=list)
    result_node = Column(String, default="")
    result_name = Column(String, default="")
    reason = Column(Text, default="")
    confidence = Column(Float, default=0.5)
    teacher_override = Column(Boolean, default=False)
    teacher_feedback = Column(Text, default="")
    # Enhanced decision fields
    evidence = Column(JSON, default=list)
    alternatives_considered = Column(JSON, default=list)
    rejected_alternatives_reason = Column(Text, default="")
    risk = Column(Text, default="")
    created_by = Column(String, default="alignment_agent")
    # Enhanced decision analytics
    similarity_name = Column(Float, default=0.0)
    similarity_definition = Column(Float, default=0.0)
    similarity_context = Column(Float, default=0.0)
    decision_effect = Column(Text, default="")
    # Real text integration results
    integrated_text = Column(Text, default="")
    integrated_definition = Column(Text, default="")
    source_texts = Column(JSON, default=list)
    source_textbook_count = Column(Integer, default=0)
    original_chars = Column(Integer, default=0)
    integrated_chars = Column(Integer, default=0)
    compression_ratio = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    course_id = Column(String, ForeignKey("courses.id"), nullable=True, index=True)
    type = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    total = Column(Integer, default=0)
    message = Column(String, default="")
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    error = Column(Text, default="")
    stage = Column(String, default="pending")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class RagIndexState(Base):
    __tablename__ = "rag_index_states"
    course_id = Column(String, ForeignKey("courses.id"), primary_key=True)
    status = Column(String, default="not_built")  # not_built | building | ready | failed | stale
    chunk_count = Column(Integer, default=0)
    index_method = Column(String, default="")  # bm25 | bm25_vector
    embedding_available = Column(Boolean, default=False)
    content_signature = Column(String, default="")
    error = Column(Text, default="")
    built_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(String, primary_key=True)
    role = Column(String, nullable=False)
    content = Column(Text, default="")
    related_decision_id = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


_LEGACY_COLUMNS = {
    "textbooks": {
        "course_id": "VARCHAR",
        "original_filename": "VARCHAR DEFAULT ''",
        "content_hash": "VARCHAR DEFAULT ''",
        "updated_at": "DATETIME",
        "structure_status": "VARCHAR DEFAULT 'pending'",
        "parse_warnings": "JSON",
    },
    "chapters": {
        "parent_id": "VARCHAR DEFAULT ''",
        "order_index": "INTEGER DEFAULT 0",
        "level": "INTEGER DEFAULT 1",
        "review_status": "VARCHAR DEFAULT 'unreviewed'",
        "extraction_status": "VARCHAR DEFAULT 'pending'",
        "source_spans": "JSON",
    },
    "chunks": {
        "section_path": "JSON",
        "content_hash": "VARCHAR DEFAULT ''",
    },
    "knowledge_nodes": {
        "course_id": "VARCHAR",
        "canonical_concept_id": "VARCHAR",
        "review_status": "VARCHAR DEFAULT 'unreviewed'",
        "evidence_status": "VARCHAR DEFAULT 'unverified'",
        "model_version": "VARCHAR DEFAULT ''",
        "prompt_version": "VARCHAR DEFAULT ''",
        "updated_at": "DATETIME",
    },
    "knowledge_edges": {
        "course_id": "VARCHAR",
        "review_status": "VARCHAR DEFAULT 'unreviewed'",
        "model_version": "VARCHAR DEFAULT ''",
        "prompt_version": "VARCHAR DEFAULT ''",
        "updated_at": "DATETIME",
    },
    "jobs": {
        "course_id": "VARCHAR",
        "stage": "VARCHAR DEFAULT 'pending'",
        "retry_count": "INTEGER DEFAULT 0",
        "updated_at": "DATETIME",
    },
}


def _ensure_legacy_columns():
    """Add only backward-compatible columns that create_all cannot add."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name, columns in _LEGACY_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl}'
                    ))


def _bootstrap_default_course():
    """Attach legacy textbooks and graph records to a safe default course."""
    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.id == DEFAULT_COURSE_ID).first()
        if course is None:
            course = Course(
                id=DEFAULT_COURSE_ID,
                owner_id="demo_user",
                title="默认课程",
                description="由旧版教材自动迁移，可在课程设置中修改。",
                status="draft",
            )
            db.add(course)
            db.flush()

        db.query(Textbook).filter(
            (Textbook.course_id.is_(None)) | (Textbook.course_id == "")
        ).update({Textbook.course_id: DEFAULT_COURSE_ID}, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    # Backfill derived course ids without loading the existing 50k-node graph in memory.
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE knowledge_nodes
            SET course_id = (
                SELECT textbooks.course_id FROM textbooks
                WHERE textbooks.id = knowledge_nodes.textbook_id
            )
            WHERE course_id IS NULL OR course_id = ''
        """))
        connection.execute(text("""
            UPDATE knowledge_edges
            SET course_id = (
                SELECT knowledge_nodes.course_id FROM knowledge_nodes
                WHERE knowledge_nodes.id = knowledge_edges.source
            )
            WHERE course_id IS NULL OR course_id = ''
        """))


def _recover_interrupted_jobs():
    """Return interrupted durable jobs to the queue after an application restart."""
    db = SessionLocal()
    try:
        interrupted = db.query(Job).filter(Job.status.in_(("pending", "processing"))).all()
        for job in interrupted:
            job.status = "pending"
            job.message = "服务已恢复，任务正在重新排队"
            job.error = ""
            job.retry_count = (job.retry_count or 0) + 1
        db.commit()
    finally:
        db.close()
