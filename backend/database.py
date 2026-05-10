from sqlalchemy import create_engine, Column, String, Integer, Float, Text, JSON, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from backend.config import DATABASE_URL

engine = create_engine(DATABASE_URL.replace("sqlite:///", "sqlite:///"), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)

# ── Models ──

class Textbook(Base):
    __tablename__ = "textbooks"
    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    title = Column(String, nullable=False)
    format = Column(String, nullable=False)  # pdf, md, txt
    file_size = Column(Integer, default=0)
    total_pages = Column(Integer, default=0)
    total_chars = Column(Integer, default=0)
    parse_status = Column(String, default="pending")  # pending, processing, completed, failed
    graph_status = Column(String, default="pending")
    index_status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class Chapter(Base):
    __tablename__ = "chapters"
    id = Column(String, primary_key=True)
    textbook_id = Column(String, ForeignKey("textbooks.id"), nullable=False)
    title = Column(String, nullable=False)
    page_start = Column(Integer, default=0)
    page_end = Column(Integer, default=0)
    content = Column(Text, default="")
    char_count = Column(Integer, default=0)

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

class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    aliases = Column(JSON, default=[])
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
    source_sentences = Column(JSON, default=[])
    is_merged = Column(Boolean, default=False)
    merged_from = Column(JSON, default=[])
    teacher_locked = Column(Boolean, default=False)
    # Quality & granularity fields
    quality_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.5)
    granularity = Column(String, default="core_concept")
    learning_objective = Column(Text, default="")
    quality_flags = Column(JSON, default=[])
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

class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    id = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    target = Column(String, nullable=False)
    relation_type = Column(String, nullable=False)
    description = Column(String, default="")
    confidence = Column(Float, default=0.5)
    source_quote = Column(Text, default="")
    source_chunk_id = Column(String, default="")
    evidence = Column(JSON, default=[])
    created_by = Column(String, default="kg_extraction_agent")
    relation_subtype = Column(String, default="")
    direction_reason = Column(Text, default="")
    is_cross_textbook = Column(Boolean, default=False)

class IntegrationDecision(Base):
    __tablename__ = "integration_decisions"
    id = Column(String, primary_key=True)
    action = Column(String, nullable=False)  # merge, keep, remove, split
    affected_nodes = Column(JSON, default=[])
    result_node = Column(String, default="")
    result_name = Column(String, default="")
    reason = Column(Text, default="")
    confidence = Column(Float, default=0.5)
    teacher_override = Column(Boolean, default=False)
    teacher_feedback = Column(Text, default="")
    # Enhanced decision fields
    evidence = Column(JSON, default=[])
    alternatives_considered = Column(JSON, default=[])
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
    source_texts = Column(JSON, default=[])
    source_textbook_count = Column(Integer, default=0)
    original_chars = Column(Integer, default=0)
    integrated_chars = Column(Integer, default=0)
    compression_ratio = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    total = Column(Integer, default=0)
    message = Column(String, default="")
    payload = Column(JSON, default={})
    result = Column(JSON, default={})
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(String, primary_key=True)
    role = Column(String, nullable=False)
    content = Column(Text, default="")
    related_decision_id = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
