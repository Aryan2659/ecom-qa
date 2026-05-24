"""
src/models/qa_model.py
Fixes:
  #2 — Sliding-window to overcome 512-token BERT limit
  #4 — Multilingual: auto-detects language, uses xlm-roberta for non-English
"""

import logging
from typing import Optional
from transformers import pipeline

try:
    from langdetect import detect as _detect_lang
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

logger = logging.getLogger(__name__)

# Model identifiers
EN_MODEL   = "deepset/roberta-base-squad2"             # Upgrade: RoBERTa > BERT on SQuAD2 (~10% better F1)
MULTI_MODEL = "deepset/xlm-roberta-base-squad2"        # 100+ languages  — Fix #4

CONFIDENCE_LABELS = {
    (0.70, 1.01): "High",
    (0.40, 0.70): "Medium",
    (0.00, 0.40): "Low",
}


def _confidence_label(score: float) -> str:
    for (lo, hi), label in CONFIDENCE_LABELS.items():
        if lo <= score < hi:
            return label
    return "Low"


class QAModel:
    """
    Wraps HuggingFace extractive QA with:
    - Automatic language detection → English BERT vs multilingual XLM-RoBERTa
    - Sliding-window chunking to handle contexts longer than 512 tokens
    """

    def __init__(self):
        self._en_pipe    = None   # lazy
        self._multi_pipe = None   # lazy

    # ── Lazy loaders ─────────────────────────────────────────────────────────
    def _get_en_pipe(self):
        if self._en_pipe is None:
            logger.info("Loading English BERT QA model (%s)…", EN_MODEL)
            self._en_pipe = pipeline(
                "question-answering",
                model=EN_MODEL,
                tokenizer=EN_MODEL,
                handle_impossible_answer=True,
            )
        return self._en_pipe

    def _get_multi_pipe(self):
        if self._multi_pipe is None:
            logger.info("Loading multilingual XLM-RoBERTa QA model (%s)…", MULTI_MODEL)
            self._multi_pipe = pipeline(
                "question-answering",
                model=MULTI_MODEL,
                tokenizer=MULTI_MODEL,
                handle_impossible_answer=True,
            )
        return self._multi_pipe

    # ── Language detection ────────────────────────────────────────────────────
    @staticmethod
    def _detect_language(text: str) -> str:
        """Returns ISO 639-1 language code, defaults to 'en' on failure."""
        if not LANGDETECT_AVAILABLE:
            return "en"
        try:
            sample = text[:500]
            return _detect_lang(sample)
        except Exception:
            return "en"

    # ── Sliding-window QA  ────────────────────────────────────────────────────
    def _sliding_window_answer(self, pipe, question: str, context: str,
                                chunk_size: int = 380, overlap: int = 60):
        """
        Fix #2: Splits context into overlapping chunks, runs QA on each,
        returns the span with the highest score.
        chunk_size / overlap are measured in whitespace-split words (fast proxy
        for tokens).  Real tokenisation would be more precise but this is a good
        practical approximation without needing a tokenizer call per chunk.
        """
        words = context.split()
        if len(words) <= chunk_size:
            # Short enough — single pass
            return pipe(question=question, context=context)

        best: Optional[dict] = None
        step = chunk_size - overlap

        for start in range(0, len(words), step):
            chunk = " ".join(words[start: start + chunk_size])
            try:
                result = pipe(question=question, context=chunk)
                # 'no_answer' scores are mapped to score=0 by HF when impossible
                if best is None or result["score"] > best["score"]:
                    best = result
                    best["_chunk_start"] = start
            except Exception as e:
                logger.warning("Chunk [%d:%d] failed: %s", start, start + chunk_size, e)
            if start + chunk_size >= len(words):
                break

        return best or {"answer": "", "score": 0.0, "start": 0, "end": 0}

    # ── Context expansion (Upgrade #5) ───────────────────────────────────────
    @staticmethod
    def _expand_with_context(answer_span: str, full_context: str, max_chars: int = 400) -> str:
        """
        Find the answer span in the context and return the full sentence(s)
        surrounding it.  Makes answers feel descriptive rather than fragmentary.
        """
        if not answer_span or len(answer_span) > 200:
            return answer_span

        idx = full_context.find(answer_span)
        if idx == -1:
            return answer_span

        # Find sentence boundaries (., !, ?) before and after the answer
        start = idx
        for _ in range(max_chars // 2):
            if start <= 0:
                break
            if full_context[start - 1] in ".!?\n" and start < idx:
                break
            start -= 1

        end = idx + len(answer_span)
        for _ in range(max_chars // 2):
            if end >= len(full_context):
                break
            if full_context[end - 1] in ".!?\n" and end > idx + len(answer_span):
                break
            end += 1

        expanded = full_context[start:end].strip(" .,;:\n")
        # Ensure the answer span is included; if expansion drifted, fall back
        if answer_span not in expanded:
            return answer_span
        # Add trailing punctuation
        if expanded and expanded[-1] not in ".!?":
            expanded += "."
        return expanded

    # ── Public interface ──────────────────────────────────────────────────────
    def answer(self, question: str, context: str) -> dict:
        """
        Returns a dict with:
            answer, confidence_score, confidence_label,
            start, end, language, model_used
        """
        if not context.strip():
            return {"answer": "No context provided.", "confidence_score": 0.0,
                    "confidence_label": "Low", "start": 0, "end": 0}

        lang = self._detect_language(context)
        is_english = lang == "en"

        pipe = self._get_en_pipe() if is_english else self._get_multi_pipe()
        model_used = EN_MODEL if is_english else MULTI_MODEL

        raw = self._sliding_window_answer(pipe, question, context)

        score   = float(raw.get("score", 0.0))
        answer  = raw.get("answer", "").strip()

        # HuggingFace returns "" for unanswerable (SQuAD 2.0 style)
        if not answer or answer.lower() in ("", "[cls]"):
            answer = "The answer could not be found in the provided text."
            score  = 0.0
            expanded_answer = answer
        else:
            # Upgrade #5: Expand the answer with surrounding sentence(s)
            expanded_answer = self._expand_with_context(answer, context)

        return {
            "answer":           expanded_answer,
            "answer_span":      answer,         # original verbatim span (for highlighting)
            "confidence_score": round(score, 4),
            "confidence_label": _confidence_label(score),
            "start":            raw.get("start", 0),
            "end":              raw.get("end", 0),
            "language":         lang,
            "model_used":       model_used,
        }
