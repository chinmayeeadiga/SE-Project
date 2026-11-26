import logging
import re
from typing import List, Dict, Tuple, Any, Optional
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Reranks candidate retrieved passages using a Cross-Encoder with robust fallback."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: Optional[CrossEncoder] = None
        self._init_failed: bool = False

    @property
    def model(self) -> Optional[CrossEncoder]:
        if self._model is None and not self._init_failed:
            try:
                self._model = CrossEncoder(self.model_name)
            except Exception as e:
                logger.warning(
                    f"Could not load CrossEncoder model '{self.model_name}': {e}. "
                    "Using lexical-semantic fallback reranker."
                )
                self._init_failed = True
        return self._model

    def _fallback_rerank(
        self,
        query: str,
        candidates: List[Tuple[Dict[str, Any], float]],
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Fallback lexical-semantic reranker if Cross-Encoder weights cannot be loaded."""
        query_words = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", query.lower()))
        scored = []
        for chunk, base_score in candidates:
            text = f"{chunk.get('section_title', '')} {chunk.get('content', '')}".lower()
            overlap_count = sum(1 for w in query_words if w in text)
            coverage = overlap_count / len(query_words) if query_words else 0.0
            # Combined score: normalized base score + coverage boost
            composite_score = (base_score * 0.6) + (coverage * 0.4)
            scored.append((chunk, composite_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def rerank(
        self,
        query: str,
        candidates: List[Tuple[Dict[str, Any], float]],
        top_k: int = 6
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Reranks candidates using the Cross-Encoder or fallback."""
        if not candidates:
            return []

        if len(candidates) <= top_k and self.model is None:
            return candidates

        model = self.model
        if model is None:
            return self._fallback_rerank(query, candidates, top_k)

        try:
            pairs = [[query, c[0]["content"]] for c in candidates]
            scores = model.predict(pairs)
            
            reranked = []
            for (chunk, _), score in zip(candidates, scores):
                reranked.append((chunk, float(score)))

            reranked.sort(key=lambda x: x[1], reverse=True)
            return reranked[:top_k]
        except Exception as e:
            logger.warning(f"CrossEncoder inference failed: {e}. Falling back to lexical-semantic rerank.")
            return self._fallback_rerank(query, candidates, top_k)
