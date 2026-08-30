import os
from dotenv import load_dotenv

load_dotenv()

# LLM config (vendor-neutral naming)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TRUST_ENV_PROXY = os.getenv("LLM_TRUST_ENV_PROXY", "false").lower() in {"1", "true", "yes"}

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

# API security and upload controls
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000",
    ).split(",")
    if origin.strip()
]
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
PUBLIC_DEMO_READ_ONLY = os.getenv("PUBLIC_DEMO_READ_ONLY", "false").lower() in {"1", "true", "yes"}
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes"}


def get_model_status() -> dict:
    return {
        "provider": LLM_PROVIDER,
        "base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
        "api_key_configured": bool(LLM_API_KEY),
        "embedding_model": EMBEDDING_MODEL,
        "compression_target": COMPRESSION_TARGET,
    }
