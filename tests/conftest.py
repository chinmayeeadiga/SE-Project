import os
import pytest
from pathlib import Path

# Ensure consistent environment for testing
os.environ["APP_ENV"] = "testing"
os.environ["LLM_PROVIDER"] = "fallback"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from src.config import settings
from src.rag.pipeline import RAGPipeline


@pytest.fixture(scope="session")
def shared_rag_pipeline():
    """Initializes and pre-ingests the shared RAG pipeline for all test suites."""
    pipeline = RAGPipeline()
    pipeline.ensure_ingested()
    return pipeline
