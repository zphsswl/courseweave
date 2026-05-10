import os
from dotenv import load_dotenv

load_dotenv()

# LLM config (vendor-neutral naming)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Embedding config
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/medessence.db")

# Chroma
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

# Knowledge graph
MAX_CHAPTER_NODES = int(os.getenv("MAX_CHAPTER_NODES", "30"))
MIN_CHAPTER_NODES = int(os.getenv("MIN_CHAPTER_NODES", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))

# Compression
COMPRESSION_TARGET = float(os.getenv("COMPRESSION_TARGET", "0.30"))

# Alignment
SIMILARITY_THRESHOLD_HIGH = float(os.getenv("SIMILARITY_THRESHOLD_HIGH", "0.92"))
SIMILARITY_THRESHOLD_LOW = float(os.getenv("SIMILARITY_THRESHOLD_LOW", "0.82"))

# Node quality
QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "0.65"))


def get_model_status() -> dict:
    return {
        "provider": LLM_PROVIDER,
        "base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
        "api_key_configured": bool(LLM_API_KEY),
        "api_key_preview": LLM_API_KEY[:12] + "***" if LLM_API_KEY else "",
        "embedding_model": EMBEDDING_MODEL,
        "compression_target": COMPRESSION_TARGET,
    }
