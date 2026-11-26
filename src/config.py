import os

os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    APP_ENV: str = "development"
    BASE_DIR: Path = BASE_DIR
    RAG_DOCS_DIR: Path = BASE_DIR / "docs" / "rag_docs"
    SDLC_DOCS_DIR: Path = BASE_DIR / "docs" / "sdlc_docs"
    VECTOR_DB_DIR: Path = BASE_DIR / "data" / "vector_db"
    BM25_INDEX_DIR: Path = BASE_DIR / "data" / "bm25_index"
    OUTPUT_DIR: Path = BASE_DIR / "outputs"

    # LLM Settings
    LLM_PROVIDER: Literal["ollama", "openai", "gemini", "mock", "fallback"] = "fallback"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral:latest"
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT_SECONDS: int = 60

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # RAG Settings
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    CROSS_ENCODER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    CHUNK_SIZE_TOKENS: int = 384
    CHUNK_OVERLAP_TOKENS: int = 64
    MAX_CHUNK_CHAR_LEN: int = 1800

    # Retrieval Settings
    DENSE_TOP_K: int = 15
    BM25_TOP_K: int = 15
    RRF_K: int = 60
    RERANK_TOP_K: int = 6

    # Logging
    LOG_LEVEL: str = "INFO"


# Global singleton instance
settings = Settings()
