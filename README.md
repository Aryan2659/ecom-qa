---
title: EcomQA
emoji: ⚡
colorFrom: indigo
colorTo: purple
sdk: docker
pinned: false
---

# EcomQA — E-Commerce Product Intelligence Engine

**Production-grade NLP pipeline: BERT QA + Flan-T5 + RAG + Multilingual + Sentiment + Smart UI**

---

## ⭐ New in v2 — High-Impact UX Features

| # | Feature | What it does |
|---|---------|--------------|
| ① | **Product Summary Card** | Auto-extracts title, price, rating, review count, and key specs the moment a URL is scraped — no need to ask. |
| ② | **Smart Question Suggestions** | Detects product type (smartphone, laptop, headphones, TV, etc.) and shows the 5 most relevant questions as clickable chips. |
| ③ | **Confidence Explanation** | Every answer now comes with a 1-line plain-English explanation of *why* the confidence score is what it is. |
| ④ | **Review Summary** | One-click extraction of top-3 praised points + top-3 complained-about points + an overall verdict line. |
| ⑤ | **Dark / Light Mode** | Theme toggle in the navbar; preference persists across sessions via `localStorage`. |

All of the above run **client-side or in pure-Python (no extra model downloads)**, so the user experience is instant.

---

## What's Under the Hood (v1 — All 11 Limitations Fixed)

| # | Fix | How |
|---|-----|-----|
| 1 | Extractive-only answers | Flan-T5-base generative fallback when BERT confidence < 40% |
| 2 | 512-token BERT limit | Sliding-window chunking with 60-token overlap |
| 3 | Scraping fragility | 3-tier stack: Playwright stealth → requests+BS4 → graceful fail + SQLite URL cache |
| 4 | English-only | Auto language detection → XLM-RoBERTa for non-English |
| 5 | No cross-section reasoning | RAG: sentence-transformers + cosine similarity retrieval |
| 6 | Binary sentiment only | 5-class star rating + per-aspect sentiment breakdown |
| 7 | Heavy cold start | All weights pre-baked into Docker image at build time |
| 8 | No e-commerce fine-tuning | `scripts/fine_tune.py` — fine-tune on Amazon QA dataset |
| 9 | Session-only history | Flask-Login auth + SQLite persistent history + CSV export |
| 10 | No multi-product comparison | Parallel async scraping + side-by-side QA + winner scoring |
---

## Architecture

```
User Input (URL or Text)
        │
        ▼
  3-Tier Scraper ──────────────► SQLite URL Cache
        │
        ▼
  Language Detection (langdetect)
        │
        ├──► English:       deepset/bert-base-cased-squad2
        └──► Other langs:   deepset/xlm-roberta-base-squad2
                │
                ▼
        Intent Router (keyword scan + DeBERTa NLI)
         │              │               │
      Factual       Subjective       Hybrid
         │              │             │+│
         ▼              ▼
    RAG Pipeline    5-class Sentiment + Aspect Analysis
(MiniLM + cosine)  (nlptown/bert-base-multilingual)
         │
         ▼
  BERT Sliding-Window QA
         │
    confidence < 40%?
         │
         ▼
  Flan-T5 Generative Fallback
         │
         ▼
  Results → UI + SQLite history
```

---

## Quick Start (Local)

```bash
git clone https://github.com/Aryan2659/ecom-qa-bert
cd ecom-qa-bert

# Linux/Mac
bash setup.sh

# Windows
setup.bat

# Run
python -m src.app
# Open http://localhost:5000
```

## Docker

```bash
docker build -t ecomqa .        # models pre-baked here (~3–4 min)
docker run -p 5000:5000 ecomqa
```

## Fine-tune on Amazon QA (optional, Fix #8)

```bash
pip install datasets accelerate
python scripts/fine_tune.py --epochs 3 --max_samples 50000 --output_dir models/bert-amazon-qa
# Then update src/models/qa_model.py: EN_MODEL = "models/bert-amazon-qa"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | Flask 3 + Flask-Login + Gunicorn |
| Extractive QA | `deepset/bert-base-cased-squad2` (English) |
| Multilingual QA | `deepset/xlm-roberta-base-squad2` |
| Generative fallback | `google/flan-t5-base` |
| Sentiment | `nlptown/bert-base-multilingual-uncased-sentiment` |
| Intent routing | Keyword scan + `cross-encoder/nli-deberta-v3-small` |
| RAG embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Scraping | Playwright (Chromium) + BeautifulSoup4 |
| Database | SQLite (auth + history + URL cache) |
| Auth | Flask-Login + bcrypt |
| Containerisation | Docker (models pre-baked) |

---

## Project Structure

```
ecom-qa-bert/
├── src/
│   ├── app.py                    # Flask routes
│   ├── models/
│   │   ├── qa_model.py           # BERT QA + sliding window + multilingual
│   │   ├── generative_model.py   # Flan-T5 fallback
│   │   ├── sentiment_model.py    # 5-class + aspect sentiment
│   │   └── intent_router.py      # Keyword + NLI router
│   ├── scraper/scraper.py        # 3-tier scraper + cache
│   ├── rag/rag_pipeline.py       # Semantic retrieval
│   ├── database/db.py            # SQLite schema + queries
│   ├── auth/auth.py              # Flask-Login user model
│   └── comparison/compare.py    # Parallel product comparison
├── templates/                    # Jinja2 HTML templates
├── static/                       # CSS + JS
├── scripts/
│   ├── download_models.py        # Pre-cache all weights
│   └── fine_tune.py              # Amazon QA fine-tuning
├── Dockerfile                    # Pre-baked weights
├── requirements.txt
└── setup.sh / setup.bat
```

---

## License

MIT
