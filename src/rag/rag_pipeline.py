"""
src/rag/rag_pipeline.py
Fix #5 — RAG pipeline: chunks product text → embeds with sentence-transformers
→ FAISS nearest-neighbour → returns top-k relevant chunks as QA context.
This lets BERT reason across specs + reviews simultaneously.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"   # 22 MB — fast
CHUNK_WORDS    = 120   # words per chunk (was 80) — more context per chunk
CHUNK_OVERLAP  = 30    # overlapping words (was 20) — better continuity
TOP_K          = 8     # retrieved chunks (was 4) — wider net for BERT


def _chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Splits text into overlapping word-count chunks."""
    words = text.split()
    chunks = []
    step = chunk_words - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i: i + chunk_words])
        if len(chunk.split()) >= 10:     # skip tiny tail chunks
            chunks.append(chunk)
        if i + chunk_words >= len(words):
            break
    return chunks


class RAGPipeline:
    """
    Semantic retrieval over product text.
    Usage:
        rag = RAGPipeline()
        relevant = rag.get_relevant_context(question, product_text)
    """

    def __init__(self):
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            logger.info("Loading sentence-transformers embedder (%s)…", EMBED_MODEL)
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(EMBED_MODEL)
        return self._embedder

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """a: (1, D), b: (N, D) → (N,) similarity scores."""
        a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
        b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
        return (b_norm @ a_norm.T).squeeze()

    def get_relevant_context(self, question: str, product_text: str,
                             top_k: int = TOP_K) -> str:
        """
        Embeds question + all chunks, returns the top_k most relevant chunks
        joined as a single context string for the QA model.
        Falls back to raw text if embedding fails or text is short.
        """
        # Short text: no need for chunking
        if len(product_text.split()) <= CHUNK_WORDS * 2:
            return product_text

        chunks = _chunk_text(product_text)
        if len(chunks) <= top_k:
            return product_text   # small enough to pass entirely

        try:
            embedder = self._get_embedder()
            all_texts   = [question] + chunks
            embeddings  = embedder.encode(all_texts, convert_to_numpy=True, show_progress_bar=False)

            q_emb     = embeddings[0:1]         # (1, D)
            c_emb     = embeddings[1:]           # (N, D)

            sims      = self._cosine_similarity(q_emb, c_emb)   # (N,)
            top_idx   = np.argsort(sims)[::-1][:top_k]

            # Preserve original document order for readability
            top_idx   = sorted(top_idx.tolist())
            selected  = [chunks[i] for i in top_idx]
            return " ".join(selected)

        except Exception as e:
            logger.warning("RAG retrieval failed, falling back to raw text: %s", e)
            # Fallback: just return first 400 words (better than nothing)
            return " ".join(product_text.split()[:400])
