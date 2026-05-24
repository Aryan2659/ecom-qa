"""
src/models/intent_router.py
Fix #11 — Replaces brittle rule-based routing with a two-stage classifier:
  Stage 1: Keyword pre-filter  (fast, handles unambiguous cases)
  Stage 2: Zero-shot NLI with cross-encoder/nli-deberta-v3-small  (ambiguous cases)
Returns: "factual" | "subjective" | "hybrid"
"""

import re
import logging
from functools import lru_cache
from transformers import pipeline

logger = logging.getLogger(__name__)

# Lighter zero-shot model (183 MB vs bart-large's 1.6 GB)
ZS_MODEL = "cross-encoder/nli-deberta-v3-small"

# Candidate labels for zero-shot classification
FACTUAL_LABEL    = "question about technical facts, specifications, or product features"
SUBJECTIVE_LABEL = "question about user opinions, satisfaction, quality, or reviews"

# ── Keyword signals ────────────────────────────────────────────────────────────
FACTUAL_SIGNALS = [
    r"\b(what is|what are|how much|how many|how long|how big|how heavy|how tall|how wide)\b",
    r"\b(dimension|weight|size|capacity|battery|watt|volt|amp|resolution|ram|storage|processor|chip|speed|range|temperature|material|color|colour|model|version|compatible|support|include|feature|specification|spec|price|cost|warranty)\b",
    r"\b(does it (have|support|come|include|work))\b",
    r"\b(is (it|this) (waterproof|compatible|available|included|supported))\b",
    r"\b(when (was|is|will))\b",
]

SUBJECTIVE_SIGNALS = [
    r"\b(good|bad|worth|recommend|reliable|durable|happy|satisfied|disappoint|regret|love|hate|like|dislike|quality|problem|issue|complaint|review|rating|experience)\b",
    r"\b(should i (buy|get|purchase|use))\b",
    r"\b(is it (good|bad|worth|reliable|recommended|worth buying))\b",
    r"\b(do (customers|users|people|buyers) (like|hate|love|recommend|complain))\b",
    r"\bhow (is|was) the (quality|experience|performance|service|packaging)\b",
]

HYBRID_SIGNALS = [
    r"\b(best|better|compare|comparison|versus|vs\.?)\b",
    r"\b(pros? and cons?|advantages?|disadvantages?|trade.?off)\b",
    r"\b(overall|verdict)\b",
]


@lru_cache(maxsize=256)
def _keyword_classify(question_lower: str):
    """Fast keyword scan.  Returns intent string or None if ambiguous."""
    factual_hits    = sum(bool(re.search(p, question_lower)) for p in FACTUAL_SIGNALS)
    subjective_hits = sum(bool(re.search(p, question_lower)) for p in SUBJECTIVE_SIGNALS)
    hybrid_hits     = sum(bool(re.search(p, question_lower)) for p in HYBRID_SIGNALS)

    if hybrid_hits:
        return "hybrid"
    if factual_hits > 0 and subjective_hits == 0:
        return "factual"
    if subjective_hits > 0 and factual_hits == 0:
        return "subjective"
    return None  # ambiguous → escalate to NLI


class IntentRouter:
    """
    Two-stage intent classifier.  The zero-shot NLI model is loaded lazily
    and only invoked when keywords are ambiguous (avoids 200ms latency hit
    on easy questions).
    """

    def __init__(self):
        self._zs_pipe = None

    def _get_zs_pipe(self):
        if self._zs_pipe is None:
            logger.info("Loading zero-shot NLI intent classifier (%s)…", ZS_MODEL)
            self._zs_pipe = pipeline(
                "zero-shot-classification",
                model=ZS_MODEL,
                tokenizer=ZS_MODEL,
            )
        return self._zs_pipe

    def _nli_classify(self, question: str) -> str:
        """Uses NLI model to disambiguate.  Returns 'factual' | 'subjective' | 'hybrid'."""
        try:
            pipe = self._get_zs_pipe()
            result = pipe(
                question,
                candidate_labels=[FACTUAL_LABEL, SUBJECTIVE_LABEL],
                hypothesis_template="This is a {}.",
            )
            top_label = result["labels"][0]
            top_score = result["scores"][0]

            # If both scores close to 0.5 → hybrid
            if abs(result["scores"][0] - result["scores"][1]) < 0.15:
                return "hybrid"

            return "factual" if top_label == FACTUAL_LABEL else "subjective"
        except Exception as e:
            logger.warning("NLI classification failed, defaulting to factual: %s", e)
            return "factual"

    def classify(self, question: str) -> str:
        """
        Returns: 'factual' | 'subjective' | 'hybrid'
        """
        q_low = question.lower().strip()

        # Stage 1: fast keyword scan
        kw_result = _keyword_classify(q_low)
        if kw_result is not None:
            return kw_result

        # Stage 2: NLI zero-shot for ambiguous cases
        return self._nli_classify(question)
