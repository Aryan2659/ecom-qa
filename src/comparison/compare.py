"""
src/comparison/compare.py
Fix #10 — Multi-product comparison.
Scrapes N URLs in parallel (ThreadPoolExecutor), runs the full QA pipeline
on each, returns side-by-side results with a winner recommendation.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

logger = logging.getLogger(__name__)

MAX_PRODUCTS = 4
SCRAPE_TIMEOUT = 25   # seconds per product


class ComparisonEngine:
    def __init__(self, qa_model, gen_model, sentiment_model,
                 intent_router, rag_pipeline, scraper):
        self.qa        = qa_model
        self.gen       = gen_model
        self.sentiment = sentiment_model
        self.router    = intent_router
        self.rag       = rag_pipeline
        self.scraper   = scraper

    # ── Single-product pipeline ───────────────────────────────────────────────
    def _process_one(self, url: str, question: str) -> dict:
        result = {"url": url, "error": None, "qa": None, "sentiment": None}
        try:
            text, source = self.scraper.scrape(url)
            result["scrape_source"] = source
            result["text_length"]   = len(text)

            intent = self.router.classify(question)
            result["intent"] = intent

            if intent in ("factual", "hybrid"):
                ctx       = self.rag.get_relevant_context(question, text)
                qa_result = self.qa.answer(question, ctx)

                if qa_result["confidence_score"] < 0.40:
                    gen_answer = self.gen.answer(question, ctx)
                    qa_result.update({"answer": gen_answer, "source": "generative"})
                else:
                    qa_result["source"] = "extractive"

                result["qa"] = qa_result

            if intent in ("subjective", "hybrid"):
                result["sentiment"] = self.sentiment.analyze(text, question)

        except Exception as e:
            result["error"] = str(e)
            logger.warning("Error processing %s: %s", url, e)

        return result

    # ── Winner recommendation ─────────────────────────────────────────────────
    @staticmethod
    def _pick_winner(products: list[dict], intent: str) -> dict:
        """
        Simple heuristic:
        - factual  → highest QA confidence score
        - subjective → highest average star rating
        - hybrid   → combined score
        """
        scored = []
        for p in products:
            if p.get("error"):
                scored.append((p, -1))
                continue
            score = 0.0
            if intent in ("factual", "hybrid") and p.get("qa"):
                score += p["qa"].get("confidence_score", 0) * 0.6
            if intent in ("subjective", "hybrid") and p.get("sentiment"):
                stars = p["sentiment"].get("average_stars", 3) / 5.0
                score += stars * 0.4
            scored.append((p, score))

        if not scored:
            return {}
        winner = max(scored, key=lambda x: x[1])
        if winner[1] < 0:
            return {}
        return {"url": winner[0]["url"], "score": round(winner[1], 3)}

    # ── Public API ────────────────────────────────────────────────────────────
    def compare(self, urls: list[str], question: str) -> dict:
        """
        Returns a comparison dict:
        {
          question: str,
          products: [{ url, qa, sentiment, intent, error, ... }, ...],
          winner:   { url, score } | {},
          metadata: { total, failed }
        }
        """
        urls = urls[:MAX_PRODUCTS]
        products = [None] * len(urls)

        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            futures = {
                pool.submit(self._process_one, url, question): idx
                for idx, url in enumerate(urls)
            }
            for future in as_completed(futures, timeout=SCRAPE_TIMEOUT * MAX_PRODUCTS):
                idx = futures[future]
                try:
                    products[idx] = future.result(timeout=SCRAPE_TIMEOUT)
                except TimeoutError:
                    products[idx] = {"url": urls[idx], "error": "Scraping timed out"}
                except Exception as e:
                    products[idx] = {"url": urls[idx], "error": str(e)}

        # Fill any None slots (shouldn't happen but safety net)
        for i, p in enumerate(products):
            if p is None:
                products[i] = {"url": urls[i], "error": "Unknown failure"}

        intent  = self.router.classify(question)
        winner  = self._pick_winner(products, intent)
        failed  = sum(1 for p in products if p.get("error"))

        return {
            "question": question,
            "products": products,
            "winner":   winner,
            "metadata": {"total": len(products), "failed": failed, "intent": intent},
        }
