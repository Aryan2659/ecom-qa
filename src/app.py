"""
src/app.py — Main Flask Application
Fixes applied: #9 (auth + history), #10 (comparison), all routes
"""

import os
import io
import csv
import secrets
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_cors import CORS

from src.database.db import Database
from src.auth.auth import User
from src.analysis.product_analyzer import (
    extract_summary, get_suggested_questions, summarise_reviews,
    explain_confidence,
)

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# ── CORS for the Chrome extension ────────────────────────────────────────────
# Allows chrome-extension:// origins to call /api/extension/* endpoints
CORS(app, resources={r"/api/extension/*": {"origins": "*"}})

# ── Flask-Login ──────────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ── Lazy singletons (avoids loading 2GB of models at import time) ────────────
_db = _qa = _gen = _sentiment = _router = _rag = _scraper = _compare = None


def get_db():
    global _db
    if _db is None:
        _db = Database()
        _db.init_tables()
    return _db


def get_models():
    global _qa, _gen, _sentiment, _router, _rag
    if _qa is None:
        from src.models.qa_model import QAModel
        from src.models.generative_model import GenerativeModel
        from src.models.sentiment_model import SentimentModel
        from src.models.intent_router import IntentRouter
        from src.rag.rag_pipeline import RAGPipeline
        _qa        = QAModel()
        _gen       = GenerativeModel()
        _sentiment = SentimentModel()
        _router    = IntentRouter()
        _rag       = RAGPipeline()
    return _qa, _gen, _sentiment, _router, _rag


def get_scraper():
    global _scraper
    if _scraper is None:
        from src.scraper.scraper import Scraper
        _scraper = Scraper(db=get_db())
    return _scraper


def get_compare():
    global _compare
    if _compare is None:
        from src.comparison.compare import ComparisonEngine
        qa, gen, sentiment, router, rag = get_models()
        _compare = ComparisonEngine(
            qa_model=qa, gen_model=gen, sentiment_model=sentiment,
            intent_router=router, rag_pipeline=rag, scraper=get_scraper()
        )
    return _compare


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id, get_db())


# ── Smart hybrid pipeline (Upgrades #1, #2, #5) + answer cache ───────────────
import hashlib
from collections import OrderedDict

_answer_cache: "OrderedDict[str, dict]" = OrderedDict()
ANSWER_CACHE_SIZE = 256


def _cache_key(question: str, context: str) -> str:
    """SHA-256 of (question + first 2k chars of context). Same Q on same product → cache hit."""
    blob = (question.strip().lower() + "||" + context[:2000]).encode("utf-8", "ignore")
    return hashlib.sha256(blob).hexdigest()[:32]


def run_smart_qa(question: str, context: str, qa, gen, rag) -> dict:
    """
    Always-on hybrid pipeline:
      1. Retrieve top-K RAG chunks
      2. Run BERT for the exact extractive span (with confidence)
      3. Run Flan-T5 in either 'enrich' mode (BERT confident) or 'answer' mode (BERT unsure)
      4. Return both, plus a 'best_answer' chosen intelligently
    Cached by (question + context-prefix) so repeats are instant.
    """
    key = _cache_key(question, context)
    if key in _answer_cache:
        # LRU bump
        _answer_cache.move_to_end(key)
        return _answer_cache[key]

    rag_ctx   = rag.get_relevant_context(question, context)
    qa_result = qa.answer(question, rag_ctx)

    score = qa_result.get("confidence_score", 0.0)
    span  = qa_result.get("answer_span", "") or qa_result.get("answer", "")

    if score >= 0.40 and span and span.lower() != "the answer could not be found in the provided text.":
        # BERT confident → enrich with generative explanation
        try:
            generative_text = gen.answer(question, rag_ctx, mode="enrich")
        except Exception:
            generative_text = ""
        # Prefer the generative if it's substantially longer and non-empty; else keep extractive
        if generative_text and len(generative_text) > len(qa_result["answer"]) * 1.3:
            qa_result["answer"]    = generative_text
            qa_result["source"]    = "hybrid"   # BERT-anchored, Flan-T5-explained
        else:
            qa_result["source"]    = "extractive"
        qa_result["generative_text"] = generative_text
    else:
        # BERT unsure → use Flan-T5 as primary
        try:
            generative_text = gen.answer(question, rag_ctx, mode="answer")
        except Exception:
            generative_text = ""
        qa_result.update({
            "answer":           generative_text or qa_result["answer"],
            "source":           "generative",
            "confidence_label": "Generated (BERT confidence low)",
            "generative_text":  generative_text,
        })

    # Save to cache
    _answer_cache[key] = qa_result
    if len(_answer_cache) > ANSWER_CACHE_SIZE:
        _answer_cache.popitem(last=False)
    return qa_result


# ── Pages ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    session.setdefault("session_id", secrets.token_hex(16))
    return render_template("index.html")


@app.route("/compare")
def compare_page():
    return render_template("compare.html")


@app.route("/history")
@login_required
def history():
    queries = get_db().get_user_history(current_user.id)
    return render_template("history.html", queries=queries)


# ── API ──────────────────────────────────────────────────────────────────────
@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400
    try:
        text, source = get_scraper().scrape(url)
        if not text:
            return jsonify({"error": "Could not extract text from this URL. Try pasting the text manually."}), 400

        # Build the product summary card + smart question suggestions
        summary     = extract_summary(text)
        suggestions = get_suggested_questions(summary.get("product_type", "generic"))

        return jsonify({
            "text":         text,
            "source":       source,
            "char_count":   len(text),
            "summary":      summary,
            "suggestions":  suggestions,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/summarize", methods=["POST"])
def summarize_text():
    """Build a summary card + suggestions from arbitrary pasted text."""
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text is required"}), 400
    summary     = extract_summary(text)
    suggestions = get_suggested_questions(summary.get("product_type", "generic"))
    return jsonify({"summary": summary, "suggestions": suggestions})


@app.route("/api/review-summary", methods=["POST"])
def review_summary():
    """Top-3 praised + top-3 complained + verdict."""
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text is required"}), 400
    return jsonify(summarise_reviews(text))


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True)
    question = data.get("question", "").strip()
    context  = data.get("context", "").strip()

    if not question or not context:
        return jsonify({"error": "Both question and context are required"}), 400

    try:
        qa, gen, sentiment, router, rag = get_models()

        intent = router.classify(question)
        result = {"intent": intent, "question": question}

        if intent in ("factual", "hybrid"):
            qa_result = run_smart_qa(question, context, qa, gen, rag)
            qa_result["confidence_explanation"] = explain_confidence(qa_result, context)
            result["qa"] = qa_result

        if intent in ("subjective", "hybrid"):
            result["sentiment"] = sentiment.analyze(context, question)

        # Persist query — Fix #9
        user_id    = current_user.id if current_user.is_authenticated else None
        answer_str = (result.get("qa") or {}).get("answer") or \
                     (result.get("sentiment") or {}).get("summary", "")
        get_db().save_query(
            user_id=user_id,
            session_id=session.get("session_id"),
            question=question,
            answer=answer_str,
            context_preview=context[:300],
            confidence=result.get("qa", {}).get("confidence_score"),
            intent=intent,
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Extension API ─────────────────────────────────────────────────────────────
# Same as /api/ask but anonymous, CORS-enabled, and skips history saving.
@app.route("/api/extension/ask", methods=["POST", "OPTIONS"])
def extension_ask():
    if request.method == "OPTIONS":
        return "", 204

    data     = request.get_json(force=True)
    question = data.get("question", "").strip()
    context  = data.get("context", "").strip()

    if not question or not context:
        return jsonify({"error": "Both question and context are required"}), 400

    try:
        qa, gen, sentiment, router, rag = get_models()

        intent = router.classify(question)
        result = {"intent": intent, "question": question}

        if intent in ("factual", "hybrid"):
            qa_result = run_smart_qa(question, context, qa, gen, rag)
            qa_result["confidence_explanation"] = explain_confidence(qa_result, context)
            result["qa"] = qa_result

        if intent in ("subjective", "hybrid"):
            result["sentiment"] = sentiment.analyze(context, question)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/extension/compare", methods=["POST", "OPTIONS"])
def extension_compare():
    """
    Compare multiple products using pre-extracted DOM text (no scraping).
    Body: { products: [{name, url, text}, ...], question: "..." }
    Returns side-by-side QA + sentiment + winner.
    """
    if request.method == "OPTIONS":
        return "", 204

    data     = request.get_json(force=True)
    products = data.get("products", [])
    question = data.get("question", "").strip()

    if len(products) < 2:
        return jsonify({"error": "Provide at least 2 products"}), 400
    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        qa, gen, sentiment, router, rag = get_models()
        intent  = router.classify(question)

        out = []
        for p in products:
            text = (p.get("text") or "").strip()
            if not text:
                out.append({"name": p.get("name", ""), "url": p.get("url", ""),
                            "error": "No text provided"})
                continue

            row = {"name": p.get("name", ""), "url": p.get("url", "")}

            if intent in ("factual", "hybrid"):
                row["qa"] = run_smart_qa(question, text, qa, gen, rag)

            if intent in ("subjective", "hybrid"):
                row["sentiment"] = sentiment.analyze(text, question)
            out.append(row)

        # Winner scoring (same heuristic as web app)
        scored = []
        for p in out:
            if p.get("error"):
                scored.append((p, -1)); continue
            s = 0.0
            if intent in ("factual","hybrid") and p.get("qa"):
                s += p["qa"].get("confidence_score", 0) * 0.6
            if intent in ("subjective","hybrid") and p.get("sentiment"):
                s += (p["sentiment"].get("average_stars", 3) / 5.0) * 0.4
            scored.append((p, s))
        winner = max(scored, key=lambda x: x[1])
        winner_obj = ({"url": winner[0]["url"], "score": round(winner[1], 3)}
                      if winner[1] >= 0 else {})

        return jsonify({"question": question, "products": out,
                        "winner": winner_obj, "intent": intent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/compare", methods=["POST"])
def compare_api():
    data     = request.get_json(force=True)
    urls     = data.get("urls", [])
    question = data.get("question", "").strip()

    if len(urls) < 2:
        return jsonify({"error": "Provide at least 2 product URLs"}), 400
    if not question:
        return jsonify({"error": "Question is required"}), 400

    try:
        results = get_compare().compare(urls, question)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/history/export")
@login_required
def export_history():
    queries = get_db().get_user_history(current_user.id)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["timestamp", "question", "answer", "confidence", "intent"])
    writer.writeheader()
    writer.writerows(queries)
    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="query_history.csv",
    )


# ── Auth ─────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        d = request.get_json(silent=True) or request.form
        user = User.authenticate(d.get("username"), d.get("password"), get_db())
        if user:
            login_user(user, remember=True)
            next_url = request.args.get("next", url_for("index"))
            return jsonify({"success": True, "redirect": next_url}) if request.is_json else redirect(next_url)
        msg = "Invalid username or password"
        return (jsonify({"error": msg}), 401) if request.is_json else render_template("auth/login.html", error=msg)
    return render_template("auth/login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        d = request.get_json(silent=True) or request.form
        try:
            User.create(d.get("username"), d.get("password"), d.get("email", ""), get_db())
            return (jsonify({"success": True})) if request.is_json else redirect(url_for("login"))
        except ValueError as e:
            return (jsonify({"error": str(e)}), 400) if request.is_json else render_template("auth/register.html", error=str(e))
    return render_template("auth/register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    log = logging.getLogger("startup")

    log.info("Initialising database…")
    get_db()

    log.info("Pre-loading models (one-time, ~30-60 seconds)…")
    qa, gen, sentiment, router, rag = get_models()
    # Warm them up so first user request is instant
    qa.answer("test", "This is a test product description for warmup.")
    rag.get_relevant_context("test", "This is a test product. " * 50)
    sentiment.analyze("This is great. Really like it.")
    router.classify("Is it good?")
    log.info("✓ All models ready. Server starting on http://localhost:5000")

    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1",
            host="0.0.0.0", port=5000, threaded=True)
