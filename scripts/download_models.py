"""
scripts/download_models.py
Fix #7 — Pre-bakes all model weights into the local HuggingFace cache.
Run once before first launch (or bake into Dockerfile RUN step):
    python scripts/download_models.py
"""

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("model_downloader")


MODELS = [
    # (task, model_id, description)
    ("question-answering",    "deepset/bert-base-cased-squad2",                    "English BERT QA"),
    ("question-answering",    "deepset/xlm-roberta-base-squad2",                   "Multilingual XLM-RoBERTa QA"),
    ("text-classification",   "nlptown/bert-base-multilingual-uncased-sentiment",  "5-class sentiment"),
    ("zero-shot-classification", "cross-encoder/nli-deberta-v3-small",             "Intent router NLI"),
    ("text2text-generation",  "google/flan-t5-base",                               "Generative fallback (Flan-T5)"),
]

SENTENCE_TRANSFORMERS = [
    "sentence-transformers/all-MiniLM-L6-v2",   # RAG embedder
]


def download_hf_pipelines():
    from transformers import pipeline
    for task, model_id, desc in MODELS:
        logger.info("Downloading  %-50s  [%s]", model_id, desc)
        try:
            _ = pipeline(task, model=model_id, tokenizer=model_id)
            logger.info("  ✓ %s cached", model_id)
        except Exception as e:
            logger.error("  ✗ Failed to download %s: %s", model_id, e)


def download_sentence_transformers():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("sentence-transformers not installed — skipping embedder download")
        return
    for model_id in SENTENCE_TRANSFORMERS:
        logger.info("Downloading  %-50s  [RAG embedder]", model_id)
        try:
            _ = SentenceTransformer(model_id)
            logger.info("  ✓ %s cached", model_id)
        except Exception as e:
            logger.error("  ✗ Failed to download %s: %s", model_id, e)


def install_playwright_browser():
    import subprocess, sys
    logger.info("Installing Playwright Chromium browser…")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
            check=True
        )
        logger.info("  ✓ Chromium installed")
    except Exception as e:
        logger.warning("  Playwright browser install failed (optional): %s", e)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pre-download all model weights")
    parser.add_argument("--skip-playwright", action="store_true")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  ecom-qa-bert  Model Pre-download")
    logger.info("=" * 60)

    download_hf_pipelines()
    download_sentence_transformers()

    if not args.skip_playwright:
        install_playwright_browser()

    logger.info("=" * 60)
    logger.info("  All models downloaded. Cold-start overhead eliminated.")
    logger.info("=" * 60)
