"""
src/models/sentiment_model.py
Fix #6 — Replaces binary SST-2 with:
  • 5-class star-rating sentiment  (nlptown/bert-base-multilingual-uncased-sentiment)
  • Aspect-level sentiment breakdown  (keyword-extracted aspects + per-sentence scoring)
Also covers Fix #4 (multilingual) for reviews.
"""

import re
import logging
from collections import defaultdict
from transformers import pipeline

logger = logging.getLogger(__name__)

SENTIMENT_MODEL = "nlptown/bert-base-multilingual-uncased-sentiment"

# Common e-commerce product aspects and their keyword triggers
ASPECT_KEYWORDS = {
    "Battery":       ["battery", "charge", "charging", "power", "mah", "backup"],
    "Display":       ["display", "screen", "resolution", "brightness", "colour", "color", "oled", "amoled", "lcd"],
    "Camera":        ["camera", "photo", "picture", "video", "megapixel", "mp", "selfie", "lens"],
    "Performance":   ["performance", "speed", "fast", "slow", "lag", "processor", "chip", "ram", "snapdragon", "apple a"],
    "Build Quality": ["build", "quality", "material", "plastic", "metal", "glass", "premium", "cheap", "durable", "fragile"],
    "Price / Value": ["price", "value", "worth", "expensive", "cheap", "affordable", "overpriced", "budget", "cost"],
    "Delivery":      ["delivery", "shipping", "packaging", "arrived", "damage", "box"],
    "Software":      ["software", "ui", "ux", "android", "ios", "update", "bloatware", "interface", "app"],
    "Sound":         ["sound", "speaker", "audio", "volume", "bass", "microphone", "earphone"],
    "Size / Weight": ["size", "weight", "heavy", "light", "compact", "bulky", "portable"],
}

STAR_MAP = {
    "1 star":  1,
    "2 stars": 2,
    "3 stars": 3,
    "4 stars": 4,
    "5 stars": 5,
}


def _star_to_sentiment(star: int) -> str:
    if star >= 4:
        return "Positive"
    if star == 3:
        return "Neutral"
    return "Negative"


class SentimentModel:
    """
    Analyses product review text and returns:
    - Overall star distribution (1–5)
    - Overall sentiment summary
    - Per-aspect sentiment breakdown
    """

    def __init__(self):
        self._pipe = None

    def _get_pipe(self):
        if self._pipe is None:
            logger.info("Loading 5-class sentiment model (%s)…", SENTIMENT_MODEL)
            self._pipe = pipeline(
                "text-classification",
                model=SENTIMENT_MODEL,
                tokenizer=SENTIMENT_MODEL,
                top_k=None,          # return all classes
                truncation=True,
                max_length=512,
            )
        return self._pipe

    # ── Sentence splitting ────────────────────────────────────────────────────
    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        # Keep only sentences with >= 5 words (filter noise)
        return [s for s in sentences if len(s.split()) >= 5]

    # ── Aspect detection ──────────────────────────────────────────────────────
    @staticmethod
    def _detect_aspects(sentence: str) -> list[str]:
        low = sentence.lower()
        return [aspect for aspect, keywords in ASPECT_KEYWORDS.items()
                if any(kw in low for kw in keywords)]

    # ── Score a single piece of text ─────────────────────────────────────────
    def _score_text(self, text: str) -> dict:
        """Returns {star_label: score} dict."""
        pipe = self._get_pipe()
        try:
            results = pipe(text[:512])[0]  # list of {label, score}
            return {r["label"]: r["score"] for r in results}
        except Exception as e:
            logger.warning("Sentiment scoring failed: %s", e)
            return {"3 stars": 1.0}

    @staticmethod
    def _best_star(scores: dict) -> int:
        return STAR_MAP.get(max(scores, key=scores.get), 3)

    # ── Public interface ──────────────────────────────────────────────────────
    def analyze(self, context: str, question: str = "") -> dict:
        """
        Analyse context text for sentiment.
        Returns overall summary + per-aspect breakdown.
        """
        sentences = self._split_sentences(context)
        if not sentences:
            return {"summary": "Not enough review text to analyse.", "aspects": {}}

        # ── Overall distribution ──────────────────────────────────────────────
        star_counts   = defaultdict(int)
        star_scores   = defaultdict(float)
        aspect_data   = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0, "sentences": []})

        for sent in sentences[:100]:    # cap at 100 sentences for latency
            scores   = self._score_text(sent)
            star     = self._best_star(scores)
            sentiment = _star_to_sentiment(star)

            star_counts[star]    += 1
            star_scores[star]    += scores.get(f"{star} stars" if star > 1 else "1 star", 0)

            for aspect in self._detect_aspects(sent):
                aspect_data[aspect][sentiment.lower()] += 1
                aspect_data[aspect]["sentences"].append({
                    "text": sent[:120],
                    "sentiment": sentiment,
                    "stars": star,
                })

        total = max(sum(star_counts.values()), 1)
        avg_stars = sum(k * v for k, v in star_counts.items()) / total

        # ── Build aspect summary ──────────────────────────────────────────────
        aspect_summary = {}
        for aspect, data in aspect_data.items():
            pos = data["positive"]
            neu = data["neutral"]
            neg = data["negative"]
            total_asp = pos + neu + neg or 1
            dominant = max(("Positive", pos), ("Neutral", neu), ("Negative", neg), key=lambda x: x[1])[0]
            aspect_summary[aspect] = {
                "dominant_sentiment": dominant,
                "positive_pct":  round(100 * pos / total_asp),
                "neutral_pct":   round(100 * neu / total_asp),
                "negative_pct":  round(100 * neg / total_asp),
                "review_count":  total_asp,
                "sample_sentences": data["sentences"][:3],
            }

        # ── Distribution percentages ──────────────────────────────────────────
        distribution = {f"{i} star{'s' if i > 1 else ''}": round(100 * star_counts.get(i, 0) / total)
                        for i in range(5, 0, -1)}

        overall_sentiment = (
            "Positive" if avg_stars >= 3.5
            else "Negative" if avg_stars < 2.5
            else "Mixed"
        )

        return {
            "summary":             f"{overall_sentiment} ({avg_stars:.1f}/5 avg across {total} sentences)",
            "average_stars":       round(avg_stars, 2),
            "overall_sentiment":   overall_sentiment,
            "star_distribution":   distribution,
            "sentences_analysed":  total,
            "aspects":             aspect_summary,
        }
