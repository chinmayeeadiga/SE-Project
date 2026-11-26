import os
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from src.rag.chunker import DocumentChunk


class PersistentVectorStore:
    """Persistent ChromaDB vector store backed by SentenceTransformers embeddings."""

    COLLECTION_NAME = "banking_rag_knowledge_base"

    def __init__(
        self,
        persist_directory: Path,
        embedding_model_name: str = "all-MiniLM-L6-v2"
    ):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.embedding_model_name = embedding_model_name

        # Initialize embedding model lazily or immediately
        self._model: Optional[SentenceTransformer] = None

        # Initialize persistent Chroma client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.embedding_model_name)
        return self._model

    def add_chunks(self, chunks: List[DocumentChunk], batch_size: int = 64) -> int:
        """Adds chunks to the vector store idempotently, skipping existing ones with same sha256."""
        if not chunks:
            return 0

        # Query existing IDs and metadata
        existing_count = self.collection.count()
        existing_data = {}
        if existing_count > 0:
            res = self.collection.get(include=["metadatas"])
            for doc_id, meta in zip(res["ids"], res["metadatas"]):
                existing_data[doc_id] = meta.get("sha256", "")

        chunks_to_add: List[DocumentChunk] = []
        for chunk in chunks:
            # Idempotency check: if ID exists and sha256 matches, skip
            if chunk.chunk_id in existing_data and existing_data[chunk.chunk_id] == chunk.sha256:
                continue
            chunks_to_add.append(chunk)

        if not chunks_to_add:
            return 0

        # Embed and insert in batches
        total_added = 0
        for i in range(0, len(chunks_to_add), batch_size):
            batch = chunks_to_add[i:i + batch_size]
            texts = [c.content for c in batch]
            ids = [c.chunk_id for c in batch]
            metadatas = [
                {
                    "doc_id": c.doc_id,
                    "doc_name": c.doc_name,
                    "source_type": c.source_type,
                    "section_title": c.section_title,
                    "clause_id": c.clause_id or "",
                    "sha256": c.sha256,
                    "char_length": c.char_length
                }
                for c in batch
            ]

            embeddings = self.model.encode(texts, show_progress_bar=False, normalize_embeddings=True).tolist()

            # Upsert into Chroma collection
            self.collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas
            )
            total_added += len(batch)

        return total_added

    def search(
        self,
        query: str,
        top_k: int = 15,
        source_type_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Dense similarity search using cosine distance converted to similarity score."""
        if self.collection.count() == 0:
            return []

        query_embedding = self.model.encode([query], show_progress_bar=False, normalize_embeddings=True).tolist()

        where_filter = None
        if source_type_filter:
            where_filter = {"source_type": source_type_filter}

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, self.collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        ranked: List[Tuple[Dict[str, Any], float]] = []
        if not results or not results["ids"] or not results["ids"][0]:
            return ranked

        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        for chunk_id, doc_text, meta, dist in zip(ids, docs, metas, distances):
            # Chroma returns cosine distance in [0, 2]; similarity = 1 - dist
            sim_score = max(0.0, 1.0 - dist)
            chunk_data = {
                "chunk_id": chunk_id,
                "doc_id": meta.get("doc_id", ""),
                "doc_name": meta.get("doc_name", ""),
                "source_type": meta.get("source_type", ""),
                "section_title": meta.get("section_title", ""),
                "clause_id": meta.get("clause_id", ""),
                "content": doc_text,
                "metadata": meta,
                "char_length": meta.get("char_length", len(doc_text)),
                "sha256": meta.get("sha256", "")
            }
            ranked.append((chunk_data, sim_score))

        return ranked

    def get_count(self) -> int:
        return self.collection.count()
