"""
src/models/generative_model.py
Fix #1 — Generative fallback using google/flan-t5-base (open-source, ~300 MB).
Fires only when BERT confidence < 40%.
"""

import logging
from transformers import T5ForConditionalGeneration, T5Tokenizer
import torch

logger = logging.getLogger(__name__)

MODEL_ID = "google/flan-t5-base"

# Max tokens for the context fed to T5 (T5 is not limited to 512 like BERT,
# but longer inputs slow inference). We truncate to keep latency acceptable.
MAX_INPUT_TOKENS  = 768
MAX_OUTPUT_TOKENS = 220


class GenerativeModel:
    """
    Uses Flan-T5-base to synthesise answers when BERT's extractive confidence
    is too low, or to ENRICH BERT's exact-span answers with explanation.
    Prompt is engineered for descriptive, salesman-like responses.
    """

    def __init__(self):
        self._tokenizer = None
        self._model     = None
        self._device    = "cuda" if torch.cuda.is_available() else "cpu"

    def _load(self):
        if self._model is None:
            logger.info("Loading Flan-T5 generative fallback (%s) on %s…", MODEL_ID, self._device)
            self._tokenizer = T5Tokenizer.from_pretrained(MODEL_ID)
            self._model     = T5ForConditionalGeneration.from_pretrained(MODEL_ID)
            self._model.to(self._device)
            self._model.eval()

    # ── Prompt engineering ────────────────────────────────────────────────────
    @staticmethod
    def _build_prompt(question: str, context: str, mode: str = "answer") -> str:
        """
        Two modes:
          mode="answer"  → standalone answer when BERT failed
          mode="enrich"  → expand on a BERT-extracted span
        """
        ctx_preview = context[:2200]   # ~550 tokens
        if mode == "enrich":
            return (
                f"You are a helpful product expert.\n"
                f"Read the product information below and give a clear, detailed answer "
                f"to the customer's question in 2-3 sentences. Be specific and quote "
                f"facts from the product info. Do not invent details.\n\n"
                f"PRODUCT INFORMATION:\n{ctx_preview}\n\n"
                f"CUSTOMER QUESTION: {question}\n\n"
                f"DETAILED ANSWER:"
            )
        return (
            f"You are a knowledgeable product assistant. Answer the customer's question "
            f"using ONLY the product information provided. Give a complete, descriptive "
            f"answer (2-4 sentences). If the answer isn't in the information, say so "
            f"clearly instead of guessing.\n\n"
            f"PRODUCT INFORMATION:\n{ctx_preview}\n\n"
            f"QUESTION: {question}\n\n"
            f"ANSWER:"
        )

    # ── Public interface ──────────────────────────────────────────────────────
    def answer(self, question: str, context: str, mode: str = "answer") -> str:
        """Returns a generated answer string. mode: 'answer' or 'enrich'."""
        self._load()

        prompt = self._build_prompt(question, context, mode)

        inputs = self._tokenizer(
            prompt,
            return_tensors="pt",
            max_length=MAX_INPUT_TOKENS,
            truncation=True,
        ).to(self._device)

        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=MAX_OUTPUT_TOKENS,
                num_beams=4,
                early_stopping=True,
                no_repeat_ngram_size=3,
                temperature=0.7,
                do_sample=False,
            )

        answer = self._tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()
        return answer if answer else "Could not generate an answer for this question."
