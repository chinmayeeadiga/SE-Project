import logging
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from src.config import settings
from src.rag.document_loader import DocumentLoader, LoadedDocument
from src.rag.chunker import LogicalChunker, DocumentChunk
from src.rag.bm25 import BM25Retriever
from src.rag.vector_store import PersistentVectorStore
from src.rag.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Shared, production-grade Hybrid RAG Pipeline.
    Combines dense embeddings + BM25 keyword search via Reciprocal Rank Fusion (RRF),
    and refines the candidates using a Cross-Encoder reranker.
    """

    def __init__(
        self,
        rag_docs_dir: Optional[Path] = None,
        sdlc_docs_dir: Optional[Path] = None,
        vector_db_dir: Optional[Path] = None,
        bm25_index_dir: Optional[Path] = None,
        embedding_model_name: Optional[str] = None,
        cross_encoder_model_name: Optional[str] = None,
        chunk_size_chars: Optional[int] = None,
        chunk_overlap_chars: Optional[int] = None,
        dense_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        rrf_k: Optional[int] = None,
        rerank_top_k: Optional[int] = None
    ):
        self.rag_docs_dir = Path(rag_docs_dir or settings.RAG_DOCS_DIR)
        self.sdlc_docs_dir = Path(sdlc_docs_dir or settings.SDLC_DOCS_DIR)
        self.vector_db_dir = Path(vector_db_dir or settings.VECTOR_DB_DIR)
        self.bm25_index_dir = Path(bm25_index_dir or settings.BM25_INDEX_DIR)

        self.dense_top_k = dense_top_k or settings.DENSE_TOP_K
        self.bm25_top_k = bm25_top_k or settings.BM25_TOP_K
        self.rrf_k = rrf_k or settings.RRF_K
        self.rerank_top_k = rerank_top_k or settings.RERANK_TOP_K

        # Initialize components
        self.loader = DocumentLoader(self.rag_docs_dir, self.sdlc_docs_dir)
        self.chunker = LogicalChunker(
            max_chunk_char_len=chunk_size_chars or settings.MAX_CHUNK_CHAR_LEN,
            overlap_char_len=chunk_overlap_chars or 250
        )
        self.bm25 = BM25Retriever()
        self.vector_store = PersistentVectorStore(
            persist_directory=self.vector_db_dir,
            embedding_model_name=embedding_model_name or settings.EMBEDDING_MODEL_NAME
        )
        self.reranker = CrossEncoderReranker(
            model_name=cross_encoder_model_name or settings.CROSS_ENCODER_MODEL_NAME
        )

        self.bm25_index_file = self.bm25_index_dir / "bm25_index.json"
        self._is_ingested = False

    def ingest_documents(self, force: bool = False) -> Dict[str, Any]:
        """Performs incremental and idempotent ingestion of all documents."""
        logger.info("Starting document ingestion...")
        docs = self.loader.load_all_documents()
        if not docs:
            logger.warning("No documents found to ingest!")
            return {"status": "empty", "documents": 0, "chunks": 0, "new_chunks": 0}

        all_chunks: List[DocumentChunk] = []
        for doc in docs:
            chunks = self.chunker.chunk_document(doc)
            all_chunks.extend(chunks)

        logger.info(f"Loaded {len(docs)} documents into {len(all_chunks)} chunks.")

        # Ingest into Vector Store idempotently
        new_vector_chunks = self.vector_store.add_chunks(all_chunks)

        # Ingest into BM25
        bm25_loaded = False
        if not force and self.bm25_index_file.exists():
            bm25_loaded = self.bm25.load(self.bm25_index_file)

        if force or not bm25_loaded or len(self.bm25.doc_ids) != len(all_chunks):
            self.bm25.add_chunks(all_chunks)
            self.bm25.save(self.bm25_index_file)

        self._is_ingested = True
        return {
            "status": "success",
            "documents_count": len(docs),
            "total_chunks": len(all_chunks),
            "new_vector_chunks_added": new_vector_chunks,
            "vector_store_total": self.vector_store.get_count()
        }

    def ensure_ingested(self) -> None:
        """Ensures knowledge base is loaded or ingests it if not already done."""
        if not self._is_ingested:
            # Check if index files exist on disk
            if self.bm25_index_file.exists() and self.vector_store.get_count() > 0:
                self.bm25.load(self.bm25_index_file)
                self._is_ingested = True
            else:
                self.ingest_documents()

    @staticmethod
    def reciprocal_rank_fusion(
        dense_results: List[Tuple[Dict[str, Any], float]],
        bm25_results: List[Tuple[Dict[str, Any], float]],
        k: int = 60
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Combines ranked candidate lists using Reciprocal Rank Fusion (RRF)."""
        rrf_scores: Dict[str, float] = {}
        chunks_map: Dict[str, Dict[str, Any]] = {}

        # Add dense ranks
        for rank, (chunk, _) in enumerate(dense_results, start=1):
            cid = chunk["chunk_id"]
            chunks_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k + rank))

        # Add BM25 ranks
        for rank, (chunk, _) in enumerate(bm25_results, start=1):
            cid = chunk["chunk_id"]
            chunks_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k + rank))

        merged = [(chunks_map[cid], score) for cid, score in rrf_scores.items()]
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        source_type_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Executes full Hybrid Retrieval pipeline:
        Dense Search + BM25 Keyword Search -> RRF Merging -> Cross-Encoder Reranking.
        """
        self.ensure_ingested()
        effective_top_k = top_k or self.rerank_top_k

        # 1. Dense vector search
        dense_hits = self.vector_store.search(
            query=query,
            top_k=self.dense_top_k,
            source_type_filter=source_type_filter
        )

        # 2. BM25 keyword search
        bm25_hits = self.bm25.search(
            query=query,
            top_k=self.bm25_top_k,
            source_type_filter=source_type_filter
        )

        # 3. Reciprocal Rank Fusion
        fused_candidates = self.reciprocal_rank_fusion(dense_hits, bm25_hits, k=self.rrf_k)

        # 4. Cross-Encoder reranking
        reranked = self.reranker.rerank(
            query=query,
            candidates=fused_candidates,
            top_k=effective_top_k
        )

        return reranked
