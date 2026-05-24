"""
src/analysis/product_analyzer.py

High-impact enhancement module for EcomQA. Adds:
  1. Product Summary Card  — auto-extract title, price, rating, key specs,
                             pros/cons from scraped text the moment a URL
                             is scraped.
  2. Smart Question Suggestions — detect product type (phone, laptop, etc.)
                                  and suggest the 5 most relevant questions.
  3. Confidence Explanation — explain WHY a confidence score is what it is
                              (matched section, exact phrase, fallback, etc.).
  4. Review Summary — extract top-3 praised and top-3 complained-about points
                      from a free-text product description / reviews blob.

Everything below is rule-based + light NLP (no extra model downloads), so it
runs in <50 ms even on the free HF Spaces CPU.
"""

import re
from collections import Counter
from typing import Dict, List, Optional


# ── Product type detection ───────────────────────────────────────────────────
PRODUCT_TYPE_KEYWORDS = {
    "smartphone": ["smartphone", "phone", "android", "ios", "mobile phone",
                   "5g", "dual sim", "rear camera", "front camera", "mah",
                   "amoled", "ram and", "snapdragon", "mediatek"],
    "laptop":     ["laptop", "notebook", "ssd", "ram ddr", "core i3",
                   "core i5", "core i7", "core i9", "ryzen", "windows 11",
                   "macbook", "thinkpad", "chromebook"],
    "headphones": ["headphone", "earphone", "earbud", "anc",
                   "active noise cancel", "wireless audio", "in-ear",
                   "over-ear", "bluetooth headset", "tws"],
    "tv":         ["smart tv", "led tv", "qled", "oled tv", "4k", "8k",
                   "hdr10", "dolby vision", "refresh rate hz",
                   "screen size inch"],
    "watch":      ["smartwatch", "smart watch", "fitness band", "step counter",
                   "heart rate monitor", "spo2", "always-on display"],
    "appliance":  ["refrigerator", "washing machine", "microwave",
                   "air conditioner", "dishwasher", "vacuum cleaner",
                   "front load", "top load", "inverter compressor"],
    "fashion":    ["t-shirt", "shirt", "trousers", "jeans", "kurta", "saree",
                   "dress", "shoes", "sneakers", "fabric", "size chart"],
    "books":      ["paperback", "hardcover", "isbn", "author", "publisher",
                   "edition", "pages count"],
    "beauty":     ["moisturizer", "serum", "shampoo", "cleanser", "lotion",
                   "sunscreen", "spf", "fragrance", "lipstick"],
    "generic":    [],
}

SUGGESTED_QUESTIONS = {
    "smartphone": [
        "What is the battery capacity?",
        "How good is the camera?",
        "Is the display AMOLED or LCD?",
        "Does it support 5G?",
        "How is the performance for gaming?",
    ],
    "laptop": [
        "What processor does it have?",
        "How much RAM and storage?",
        "What is the battery life?",
        "Is it good for video editing or gaming?",
        "Does it have a backlit keyboard?",
    ],
    "headphones": [
        "Does it have active noise cancellation?",
        "What is the battery life?",
        "How is the sound quality?",
        "Is it comfortable for long use?",
        "Does it support fast charging?",
    ],
    "tv": [
        "What is the screen resolution?",
        "What size is the display?",
        "Does it support Dolby Vision or HDR10?",
        "How many HDMI ports does it have?",
        "Is the smart OS responsive?",
    ],
    "watch": [
        "What is the battery life?",
        "Does it track SpO2 and heart rate?",
        "Is it water resistant?",
        "Does it work with both iOS and Android?",
        "What sports modes does it support?",
    ],
    "appliance": [
        "What is the capacity in litres or kg?",
        "How energy-efficient is it?",
        "Is it noisy during operation?",
        "What is the warranty period?",
        "How easy is it to clean?",
    ],
    "fashion": [
        "What is the fabric material?",
        "How is the fit and sizing?",
        "Is it machine washable?",
        "Does the colour fade after wash?",
        "Is the stitching good quality?",
    ],
    "books": [
        "Who is the author?",
        "How many pages does it have?",
        "What edition is this?",
        "Is the print quality good?",
        "Is it suitable for beginners?",
    ],
    "beauty": [
        "What are the key ingredients?",
        "Is it suitable for sensitive skin?",
        "Does it contain parabens or sulfates?",
        "What is the shelf life?",
        "Is it cruelty-free?",
    ],
    "generic": [
        "What is the price?",
        "Is it worth the money?",
        "How is the build quality?",
        "What do customers complain about?",
        "What are the main features?",
    ],
}


# ── Praise / complaint markers ───────────────────────────────────────────────
PRAISE_MARKERS = [
    "love", "great", "excellent", "amazing", "perfect", "fantastic",
    "awesome", "outstanding", "superb", "wonderful", "best", "good",
    "impressive", "satisfied", "recommend", "value for money", "worth",
    "highly recommend", "stunning", "beautiful", "smooth", "fast",
    "premium", "quality", "comfortable", "reliable",
]

COMPLAINT_MARKERS = [
    "terrible", "horrible", "awful", "worst", "bad", "poor",
    "disappointed", "disappointing", "useless", "waste", "broken",
    "defective", "issue", "problem", "fault", "stopped working",
    "doesn't work", "not working", "annoying", "buggy", "slow",
    "cheap", "flimsy", "uncomfortable", "expensive for", "overpriced",
    "regret", "avoid", "returned", "refund",
]


# ── Helpers ──────────────────────────────────────────────────────────────────
def _normalise(text: str) -> str:
    if not text:
        return ""
    # Collapse runs of horizontal whitespace but preserve newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sents if s and len(s.strip()) > 10]


def detect_product_type(text: str) -> str:
    """Return the product category that best matches the text. Defaults 'generic'."""
    lower = text.lower()
    scores = {}
    for ptype, kws in PRODUCT_TYPE_KEYWORDS.items():
        if not kws:
            continue
        scores[ptype] = sum(1 for kw in kws if kw in lower)
    best = max(scores.items(), key=lambda x: x[1]) if scores else ("generic", 0)
    return best[0] if best[1] >= 1 else "generic"


def get_suggested_questions(product_type: str) -> List[str]:
    return SUGGESTED_QUESTIONS.get(product_type, SUGGESTED_QUESTIONS["generic"])


# ── Product Summary Card ─────────────────────────────────────────────────────
PRICE_PATTERNS = [
    r"(?:₹|Rs\.?|INR)\s?([0-9][0-9,]*)(?:\.[0-9]{1,2})?",
    r"\$\s?([0-9][0-9,]*)(?:\.[0-9]{1,2})?",
    r"£\s?([0-9][0-9,]*)(?:\.[0-9]{1,2})?",
    r"€\s?([0-9][0-9,]*)(?:\.[0-9]{1,2})?",
]
RATING_PATTERN = r"([0-5](?:\.[0-9])?)\s*(?:out\s*of|/)\s*5"
REVIEW_COUNT_PATTERN = r"([0-9](?:[0-9,]{1,12})?)[ \t]+(?:ratings?|reviews?)\b"


def extract_summary(text: str) -> Dict:
    """
    Build a Product Summary Card from raw scraped text.
    Returns a dict with title, price, rating, review_count, key_specs (list),
    and the detected product_type.
    """
    text = _normalise(text)
    if not text:
        return {}

    # ── Title — split by line, then by sentence; pick first product-like one
    title = ""
    # First try splitting on newlines (raw text often has these)
    lines = [l.strip(" |·-•") for l in re.split(r"[\r\n]+", text) if l.strip()]
    if not lines or len(lines) < 2:
        # Single-blob text: fall back to sentence splitting
        lines = [s.strip(" |·-•") for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    for line in lines[:10]:
        low = line.lower()
        if not line:
            continue
        # Skip lines that are obviously not titles
        if any(low.startswith(p) for p in ("price", "rs", "₹", "$", "rating",
                                           "battery", "ram", "storage", "display",
                                           "camera", "processor", "the phone",
                                           "the ", "however", "worth", "highly",
                                           "buy now", "add to cart", "from ",
                                           "free delivery")):
            continue
        # Skip review-style sentences
        if any(re.search(rf"\b{w}\b", low) for w in (
                "amazing", "terrible", "great", "good", "bad", "worst",
                "best", "love", "hate", "awesome", "horrible")):
            continue
        if 15 <= len(line) <= 180:
            title = line.rstrip(".,:;")
            break
    if not title:
        title = (text[:120] + "…") if len(text) > 120 else text

    # ── Price ────────────────────────────────────────────────────────────────
    price = None
    price_currency = None
    for pat in PRICE_PATTERNS:
        m = re.search(pat, text)
        if m:
            price = m.group(0).strip()
            price_currency = m.group(0)[0]
            break

    # ── Rating ───────────────────────────────────────────────────────────────
    rating = None
    rm = re.search(RATING_PATTERN, text, re.IGNORECASE)
    if rm:
        try:
            rating = float(rm.group(1))
            if rating > 5: rating = None
        except ValueError:
            rating = None

    # ── Review count ────────────────────────────────────────────────────────
    review_count = None
    rcm = re.search(REVIEW_COUNT_PATTERN, text, re.IGNORECASE)
    if rcm:
        cleaned = rcm.group(1).replace(",", "")
        try:
            n = int(cleaned)
            if n >= 1:
                review_count = str(n)
        except ValueError:
            pass

    # ── Key specs — look for short "Key: Value" patterns ────────────────────
    key_specs = []
    # Match "Key: short_value" up to next newline or strong delimiter
    spec_keys = ["Battery", "RAM", "Storage", "Display", "Screen", "Camera",
                 "Processor", "Weight", "Resolution", "Refresh Rate",
                 "Capacity", "Wattage", "Voltage", "Warranty", "Colour", "Color"]
    seen_keys = set()
    for key in spec_keys:
        # Try "Key: value" form (most reliable)
        m = re.search(rf"\b{re.escape(key)}\s*[:\-]\s*([^\n.,;|]{{2,40}})", text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".,;|")
            # Stop value at the next key word if any
            for other_key in spec_keys:
                if other_key.lower() != key.lower():
                    pos = val.lower().find(other_key.lower())
                    if pos > 0:
                        val = val[:pos].strip().rstrip(".,;|")
            if 2 <= len(val) <= 40 and key.lower() not in seen_keys:
                seen_keys.add(key.lower())
                key_specs.append({"key": key.title(), "value": val})
                if len(key_specs) >= 6:
                    break

    return {
        "title":         title,
        "price":         price,
        "currency":      price_currency,
        "rating":        rating,
        "review_count":  review_count,
        "key_specs":     key_specs,
        "product_type":  detect_product_type(text),
        "char_count":    len(text),
    }


# ── Review Summary ───────────────────────────────────────────────────────────
def summarise_reviews(text: str, max_per_side: int = 3) -> Dict:
    """
    Extract the top-3 praised aspects and top-3 complained-about aspects
    from free-text reviews/description.

    Heuristic-only. No ML, but it's robust enough to produce a usable
    summary on any product page that contains review snippets.
    """
    text = _normalise(text)
    if not text:
        return {"praised": [], "complained": [], "verdict": ""}

    sentences = _split_sentences(text)
    praised, complained = [], []

    # Skip sentences that look like product header/spec lines (have prices,
    # ratings, "ratings"/"reviews" counts) — they often contain "great" or
    # similar words by coincidence (e.g. "Great deal at $199")
    spec_indicators = re.compile(
        r"(?:₹|Rs\.?|INR|\$|£|€)\s?\d|"           # prices
        r"\d+\s*(?:mAh|GB|TB|MB|inch|kg|cm|MP|Hz)|"  # units
        r"\d+\s*(?:ratings?|reviews?|stars?)|"     # rating counts
        r"\b(?:out of|/)\s*5\b",                    # rating fractions
        re.IGNORECASE,
    )

    for sent in sentences:
        if spec_indicators.search(sent):
            continue
        low = sent.lower()
        # Word-boundary match so "good" matches "good", not "goods"
        praise_hits   = sum(1 for k in PRAISE_MARKERS    if re.search(rf"\b{re.escape(k)}\b", low))
        complaint_hits = sum(1 for k in COMPLAINT_MARKERS if re.search(rf"\b{re.escape(k)}\b", low))
        # Pick the dominant tone
        if praise_hits > complaint_hits and praise_hits >= 1:
            praised.append(sent)
        elif complaint_hits > praise_hits and complaint_hits >= 1:
            complained.append(sent)

    # Deduplicate by first-30-chars signature and clip
    def _dedup(items: List[str], n: int) -> List[str]:
        seen = set()
        out  = []
        for s in items:
            sig = s.lower()[:30]
            if sig in seen:
                continue
            seen.add(sig)
            # Trim to one sentence, max 180 chars
            out.append(s[:180].rstrip(",;") + ("…" if len(s) > 180 else ""))
            if len(out) >= n:
                break
        return out

    praised_top    = _dedup(praised,    max_per_side)
    complained_top = _dedup(complained, max_per_side)

    # ── Verdict line ────────────────────────────────────────────────────────
    if praised_top and not complained_top:
        verdict = "Overall, reviewers are very positive about this product."
    elif complained_top and not praised_top:
        verdict = "Reviewers report several issues — proceed with caution."
    elif praised_top and complained_top:
        if len(praised_top) > len(complained_top):
            verdict = "Mostly positive feedback, with a few notable complaints."
        elif len(complained_top) > len(praised_top):
            verdict = "Mixed feedback — significant complaints alongside positive notes."
        else:
            verdict = "Mixed reviews — opinions are split roughly evenly."
    else:
        verdict = "Not enough opinion-bearing text to summarise reviews."

    return {
        "praised":     praised_top,
        "complained":  complained_top,
        "verdict":     verdict,
        "praise_count":    len(praised),
        "complaint_count": len(complained),
    }


# ── Confidence Explanation ───────────────────────────────────────────────────
def explain_confidence(qa_result: Dict, context: str) -> str:
    """
    Generate a human-readable, 1-line explanation of why the confidence
    score is what it is. Examples:
      "High — exact match found in product specifications."
      "Medium — answer paraphrased from a single review."
      "Low — model fell back to a generative guess."
    """
    if not qa_result:
        return ""

    score   = qa_result.get("confidence_score", 0.0) or 0.0
    source  = (qa_result.get("source") or "").lower()
    answer  = (qa_result.get("answer") or "").strip()
    context = context or ""
    low_ctx = context.lower()
    low_ans = answer.lower()

    in_specs = any(k in low_ctx for k in ("specifications", "key features",
                                          "technical details", "product details"))
    # Did the answer appear verbatim in the context?
    exact_match = bool(answer) and low_ans[:50] in low_ctx

    if source == "generative" or score < 0.30:
        return ("Low — extractive model could not find a direct match, so the "
                "answer was generated from the surrounding text.")
    if source == "hybrid":
        return ("High — BERT located the answer in the text, and Flan-T5 "
                "expanded it into a fuller explanation.")
    if exact_match and in_specs:
        return "High — exact phrase matched in the product specifications section."
    if exact_match:
        return "High — exact phrase matched in the product description."
    if score >= 0.70:
        return "High — model identified a strong matching span in the text."
    if score >= 0.40:
        return "Medium — model found a plausible match but not a verbatim one."
    return "Low — weak signal; consider rephrasing the question."
