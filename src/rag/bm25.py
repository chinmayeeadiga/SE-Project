import json
import math
import re
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
from src.rag.chunker import DocumentChunk


# Common English stopwords to improve BM25 precision
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "isn't", "it", "it's", "its", "itself", "just", "me", "more", "most", "mustn't", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out",
    "over", "own", "same", "shan't", "she", "should", "shouldn't", "so", "some", "such", "than", "that", "the",
    "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "wasn't", "we", "were", "weren't", "what", "when", "where",
    "which", "while", "who", "whom", "why", "with", "won't", "would", "wouldn't", "you", "your", "yours",
    "yourself", "yourselves"
}


class BM25Retriever:
    """Production-grade, persistent BM25Okapi retrieval engine."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: List[str] = []
        self.chunks_map: Dict[str, Dict[str, Any]] = {}
        self.doc_lengths: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_count: int = 0
        self.inverted_index: Dict[str, Dict[int, int]] = {}  # term -> {doc_idx: freq}
        self.idf: Dict[str, float] = {}

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenizes and normalizes text for keyword matching."""
        tokens = re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())
        return [t for t in tokens if t not in STOPWORDS]

    def add_chunks(self, chunks: List[DocumentChunk]) -> None:
        """Indexes document chunks into the BM25 inverted index."""
        self.doc_ids = []
        self.chunks_map = {}
        self.doc_lengths = []
        self.inverted_index = {}
        self.idf = {}

        total_length = 0

        for idx, chunk in enumerate(chunks):
            self.doc_ids.append(chunk.chunk_id)
            self.chunks_map[chunk.chunk_id] = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_name": chunk.doc_name,
                "source_type": chunk.source_type,
                "section_title": chunk.section_title,
                "clause_id": chunk.clause_id,
                "content": chunk.content,
                "metadata": chunk.metadata,
                "char_length": chunk.char_length,
                "sha256": chunk.sha256,
            }

            tokens = self.tokenize(f"{chunk.section_title} {chunk.content}")
            length = len(tokens)
            self.doc_lengths.append(length)
            total_length += length

            # Count term frequencies in this document
            tf: Dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1

            for token, count in tf.items():
                if token not in self.inverted_index:
                    self.inverted_index[token] = {}
                self.inverted_index[token][idx] = count

        self.doc_count = len(self.doc_ids)
        self.avg_doc_len = total_length / self.doc_count if self.doc_count > 0 else 0.0

        # Calculate IDF for all indexed terms
        for term, postings in self.inverted_index.items():
            doc_freq = len(postings)
            # Standard Lucene/BM25 Okapi smoothed IDF
            self.idf[term] = math.log(1.0 + (self.doc_count - doc_freq + 0.5) / (doc_freq + 0.5))

    def search(
        self,
        query: str,
        top_k: int = 15,
        source_type_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Scores documents matching query terms using BM25Okapi."""
        if not self.doc_ids:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        scores: Dict[int, float] = {}

        for token in query_tokens:
            if token not in self.inverted_index:
                continue

            idf = self.idf.get(token, 0.0)
            postings = self.inverted_index[token]

            for doc_idx, freq in postings.items():
                doc_len = self.doc_lengths[doc_idx]
                denom = freq + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                term_score = idf * (freq * (self.k1 + 1.0)) / denom if denom > 0 else 0.0
                scores[doc_idx] = scores.get(doc_idx, 0.0) + term_score

        # Filter by source_type if requested
        ranked = []
        for doc_idx, score in scores.items():
            chunk_id = self.doc_ids[doc_idx]
            chunk_data = self.chunks_map[chunk_id]
            if source_type_filter and chunk_data["source_type"] != source_type_filter:
                continue
            ranked.append((chunk_data, score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    def save(self, filepath: Path) -> None:
        """Persists the BM25 index and metadata to disk."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "chunks_map": self.chunks_map,
            "doc_lengths": self.doc_lengths,
            "avg_doc_len": self.avg_doc_len,
            "doc_count": self.doc_count,
            "inverted_index": self.inverted_index,
            "idf": self.idf
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def load(self, filepath: Path) -> bool:
        """Loads a persisted BM25 index."""
        filepath = Path(filepath)
        if not filepath.exists():
            return False

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.k1 = data["k1"]
        self.b = data["b"]
        self.doc_ids = data["doc_ids"]
        self.chunks_map = data["chunks_map"]
        self.doc_lengths = data["doc_lengths"]
        self.avg_doc_len = data["avg_doc_len"]
        self.doc_count = data["doc_count"]
        # Convert string keys back to int for doc_idx in postings
        self.inverted_index = {
            term: {int(idx): count for idx, count in postings.items()}
            for term, postings in data["inverted_index"].items()
        }
        self.idf = data["idf"]
        return True
