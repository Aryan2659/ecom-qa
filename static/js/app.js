/* ════════════════════════════════════════════════════════════
   EcomQA — app.js  (v2 with: summary card, suggestions,
   confidence explanation, review summary, dark/light toggle)
   ════════════════════════════════════════════════════════════ */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let currentContext = "";
const sessionHistory = [];

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ════════════════════════════════════════════════════════════
//  FEATURE: Dark / Light theme toggle
// ════════════════════════════════════════════════════════════
(function initTheme() {
  const btn = $("themeToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const html = document.documentElement;
    const next = html.getAttribute("data-theme") === "light" ? "dark" : "light";
    html.setAttribute("data-theme", next);
    try { localStorage.setItem("ecomqa-theme", next); } catch (e) {}
  });
})();

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    const panel = tab.dataset.tab;
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + panel).classList.add("active");
  });
});

// ── Char count for text mode ──────────────────────────────────────────────────
const textInput = $("textInput");
if (textInput) {
  textInput.addEventListener("input", () => {
    $("charCount").textContent = textInput.value.length.toLocaleString();
    currentContext = textInput.value.trim();
  });
}

// ── Analyze pasted text button (text-mode counterpart of scrape) ─────────────
$("analyzeTextBtn")?.addEventListener("click", async () => {
  const text = textInput?.value.trim();
  if (!text) return alert("Paste some text first.");
  try {
    const res = await fetch("/api/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    renderSummaryCard(data.summary);
    renderSuggestions(data.suggestions);
  } catch (e) {
    alert("Could not analyze text: " + e.message);
  }
});

// ── Scrape ────────────────────────────────────────────────────────────────────
const scrapeBtn = $("scrapeBtn");
if (scrapeBtn) {
  scrapeBtn.addEventListener("click", async () => {
    const url = $("urlInput").value.trim();
    if (!url) return setStatus("Please enter a URL.", "warn");

    setStatus("Scraping product page…", "info");
    scrapeBtn.disabled = true;

    try {
      const res  = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);

      currentContext = data.text;
      setStatus(
        `✓ Scraped via ${data.source} — ${data.char_count.toLocaleString()} characters extracted`,
        "success"
      );
      // Render the new product summary card + suggestions
      renderSummaryCard(data.summary);
      renderSuggestions(data.suggestions);
    } catch (e) {
      setStatus("✗ " + e.message, "error");
    } finally {
      scrapeBtn.disabled = false;
    }
  });
}

function setStatus(msg, type = "info") {
  const el = $("scrapeStatus");
  if (!el) return;
  const colours = { info: "var(--text-muted)", success: "var(--success)",
                    warn: "var(--warn)", error: "var(--danger)" };
  el.textContent   = msg;
  el.style.color   = colours[type] || colours.info;
}

// ════════════════════════════════════════════════════════════
//  FEATURE: Product Summary Card (Feature #1)
// ════════════════════════════════════════════════════════════
function renderSummaryCard(summary) {
  if (!summary || !summary.title) {
    $("summaryCard")?.classList.add("hidden");
    return;
  }
  const card = $("summaryCard");
  card.classList.remove("hidden");

  $("summaryTitle").textContent       = summary.title || "—";
  $("productTypeBadge").textContent   = (summary.product_type || "generic")
    .charAt(0).toUpperCase() + (summary.product_type || "generic").slice(1);

  // Price
  const priceWrap = $("statPrice");
  if (summary.price) {
    priceWrap.classList.remove("hidden");
    $("statPriceVal").textContent = summary.price;
  } else { priceWrap.classList.add("hidden"); }

  // Rating
  const ratingWrap = $("statRating");
  if (summary.rating != null) {
    ratingWrap.classList.remove("hidden");
    const r = Math.round(summary.rating);
    $("statRatingVal").innerHTML =
      "★".repeat(r) + "☆".repeat(Math.max(0, 5 - r)) + ` ${summary.rating}/5`;
  } else { ratingWrap.classList.add("hidden"); }

  // Review count
  const rcWrap = $("statReviews");
  if (summary.review_count) {
    rcWrap.classList.remove("hidden");
    $("statReviewsVal").textContent =
      Number(summary.review_count).toLocaleString() + " reviews";
  } else { rcWrap.classList.add("hidden"); }

  // Key specs grid
  const grid = $("specGrid");
  grid.innerHTML = "";
  if (Array.isArray(summary.key_specs) && summary.key_specs.length) {
    summary.key_specs.forEach(s => {
      const item = document.createElement("div");
      item.className = "spec-item";
      item.innerHTML = `<div class="spec-key">${escHtml(s.key)}</div>
                        <div class="spec-val">${escHtml(s.value)}</div>`;
      grid.appendChild(item);
    });
  }
}

// ════════════════════════════════════════════════════════════
//  FEATURE: Smart Question Suggestions (Feature #2)
// ════════════════════════════════════════════════════════════
function renderSuggestions(suggestions) {
  const card = $("suggestionsCard");
  const wrap = $("suggestionChips");
  if (!wrap || !card) return;
  if (!Array.isArray(suggestions) || suggestions.length === 0) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  wrap.innerHTML = "";
  suggestions.forEach(q => {
    const chip = document.createElement("button");
    chip.className   = "chip";
    chip.type        = "button";
    chip.textContent = q;
    chip.addEventListener("click", () => {
      $("questionInput").value = q;
      $("questionInput").focus();
      handleAsk();
    });
    wrap.appendChild(chip);
  });
}

// ── Ask ───────────────────────────────────────────────────────────────────────
const askBtn = $("askBtn");
if (askBtn) {
  askBtn.addEventListener("click", handleAsk);
  $("questionInput")?.addEventListener("keydown", e => {
    if (e.key === "Enter") handleAsk();
  });
}

async function handleAsk() {
  const question = $("questionInput").value.trim();
  const context  = currentContext ||
                   ($("textInput") ? $("textInput").value.trim() : "");

  if (!question) return alert("Please enter a question.");
  if (!context)  return alert("Please scrape a URL or paste text first.");

  showLoader(true, "Running BERT + RAG pipeline…");

  try {
    const res  = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    renderAnswer(data, context);
    addToSessionHistory(data);
  } catch (e) {
    alert("Error: " + e.message);
  } finally {
    showLoader(false);
  }
}

// ── Render answer ─────────────────────────────────────────────────────────────
function renderAnswer(data, context) {
  const panel = $("answerPanel");
  panel.classList.remove("hidden");

  // Intent badge
  const ib = $("intentBadge");
  if (ib) {
    ib.textContent = capitalize(data.intent);
    ib.className   = "badge badge-intent";
  }

  // QA result
  const qaDiv = $("qaResult");
  if (data.qa && qaDiv) {
    qaDiv.classList.remove("hidden");
    $("answerText").textContent = data.qa.answer;

    const confBadge = $("confidenceBadge");
    const confScore = data.qa.confidence_score;
    confBadge.textContent = `${data.qa.confidence_label} (${pct(confScore)})`;
    confBadge.className   = `badge badge-${confScore >= 0.7 ? "high" : confScore >= 0.4 ? "medium" : "low"}`;

    $("sourceBadge").textContent = capitalize(data.qa.source || "");
    $("langBadge").textContent   = (data.qa.language || "en").toUpperCase();

    // FEATURE #3: Confidence Explanation
    const ce = $("confidenceExplanation");
    if (data.qa.confidence_explanation) {
      ce.classList.remove("hidden");
      ce.textContent = "🔍 " + data.qa.confidence_explanation;
    } else {
      ce.classList.add("hidden");
    }

    // Highlight in context
    if (data.qa.answer && data.qa.source !== "generative") {
      const highlighted = highlightSpan(context, data.qa.answer);
      if (highlighted) {
        $("highlightedContext").innerHTML = highlighted;
        $("highlightSection").classList.remove("hidden");
      } else {
        $("highlightSection").classList.add("hidden");
      }
    } else {
      $("highlightSection").classList.add("hidden");
    }
  } else if (qaDiv) {
    qaDiv.classList.add("hidden");
  }

  // Sentiment result
  const sentDiv = $("sentimentResult");
  if (data.sentiment && sentDiv) {
    sentDiv.classList.remove("hidden");
    renderSentiment(data.sentiment);
  } else if (sentDiv) {
    sentDiv.classList.add("hidden");
  }

  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSentiment(s) {
  // Stars
  const stars  = Math.round(s.average_stars);
  $("avgStars").textContent       = "★".repeat(stars) + "☆".repeat(5 - stars) + ` ${s.average_stars}/5`;
  $("overallSentiment").textContent = s.overall_sentiment;
  $("overallSentiment").style.color =
    s.overall_sentiment === "Positive" ? "var(--success)" :
    s.overall_sentiment === "Negative" ? "var(--danger)"  : "var(--warn)";

  // Star distribution bars
  const distEl = $("starDistribution");
  distEl.innerHTML = Object.entries(s.star_distribution).map(([label, pctVal]) => `
    <div class="star-row">
      <span style="min-width:52px;font-size:.8rem;color:var(--text-muted)">${label}</span>
      <div class="star-bar-bg"><div class="star-bar-fill" style="width:${pctVal}%"></div></div>
      <span class="star-pct">${pctVal}%</span>
    </div>`).join("");

  // Aspects
  const aspectEl = $("aspectGrid");
  if (!s.aspects || Object.keys(s.aspects).length === 0) {
    aspectEl.innerHTML = `<p style="color:var(--text-dim);font-size:.85rem">No specific aspects detected in this text.</p>`;
    return;
  }
  aspectEl.innerHTML = Object.entries(s.aspects).map(([name, a]) => {
    const dom = a.dominant_sentiment;
    const color = dom === "Positive" ? "var(--success)" : dom === "Negative" ? "var(--danger)" : "var(--warn)";
    return `
      <div class="aspect-card">
        <div class="aspect-name">${name}</div>
        <div class="aspect-bar-row">
          <div class="aspect-bar-pos" style="flex:${a.positive_pct}"></div>
          <div class="aspect-bar-neu" style="flex:${a.neutral_pct}"></div>
          <div class="aspect-bar-neg" style="flex:${a.negative_pct}"></div>
        </div>
        <span style="font-size:.78rem;color:${color};font-weight:600">${dom}</span>
        <span style="font-size:.75rem;color:var(--text-dim)"> · ${a.review_count} mentions</span>
      </div>`;
  }).join("");
}

// ════════════════════════════════════════════════════════════
//  FEATURE: Review Summary (Feature #5)
// ════════════════════════════════════════════════════════════
$("generateReviewSummaryBtn")?.addEventListener("click", async () => {
  const context = currentContext ||
                  ($("textInput") ? $("textInput").value.trim() : "");
  if (!context) return alert("Please scrape a URL or paste text first.");

  showLoader(true, "Summarising reviews…");
  try {
    const res = await fetch("/api/review-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: context }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    renderReviewSummary(data);
  } catch (e) {
    alert("Error: " + e.message);
  } finally {
    showLoader(false);
  }
});

function renderReviewSummary(data) {
  $("reviewSummaryResult").classList.remove("hidden");
  $("reviewVerdict").textContent = data.verdict || "";

  const praisedList    = $("praisedList");
  const complainedList = $("complainedList");
  praisedList.innerHTML    = "";
  complainedList.innerHTML = "";

  if (Array.isArray(data.praised) && data.praised.length) {
    data.praised.forEach(s => {
      const li = document.createElement("li");
      li.textContent = s;
      praisedList.appendChild(li);
    });
  } else {
    praisedList.innerHTML = `<li class="muted-text">No praise-bearing sentences found.</li>`;
  }

  if (Array.isArray(data.complained) && data.complained.length) {
    data.complained.forEach(s => {
      const li = document.createElement("li");
      li.textContent = s;
      complainedList.appendChild(li);
    });
  } else {
    complainedList.innerHTML = `<li class="muted-text">No complaint-bearing sentences found.</li>`;
  }
}

// ── Session history ───────────────────────────────────────────────────────────
function addToSessionHistory(data) {
  const question = $("questionInput").value.trim();
  const answer   = data.qa?.answer || data.sentiment?.summary || "";
  sessionHistory.unshift({ question, answer, intent: data.intent,
                            confidence: data.qa?.confidence_score });
  renderSessionHistory();
}

function renderSessionHistory() {
  const list      = $("historyList");
  const countEl   = $("historyCount");
  const clearBtn  = $("clearHistoryBtn");
  if (!list) return;

  countEl.textContent = sessionHistory.length;
  clearBtn?.classList.toggle("hidden", sessionHistory.length === 0);

  list.innerHTML = sessionHistory.slice(0, 20).map((item, i) => `
    <div class="history-item">
      <div class="history-q">${escHtml(item.question)}</div>
      <div class="history-a">${escHtml(item.answer.slice(0, 120))}${item.answer.length > 120 ? "…" : ""}</div>
      <div class="history-meta">
        <span class="badge badge-intent">${capitalize(item.intent)}</span>
        ${item.confidence != null
          ? `<span class="badge badge-${item.confidence >= 0.7 ? "high" : item.confidence >= 0.4 ? "medium" : "low"}">${pct(item.confidence)}</span>`
          : ""}
      </div>
    </div>`).join("");
}

$("clearHistoryBtn")?.addEventListener("click", () => {
  sessionHistory.length = 0;
  renderSessionHistory();
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function showLoader(on, msg = "Processing…") {
  const el = $("loader");
  if (!el) return;
  el.classList.toggle("hidden", !on);
  const msgEl = $("loaderMsg");
  if (msgEl) msgEl.textContent = msg;
}

function pct(score) { return Math.round((score || 0) * 100) + "%"; }
function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }
function escHtml(s) { return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

function highlightSpan(context, answer) {
  if (!answer || !context) return null;
  const idx = context.indexOf(answer);
  if (idx === -1) return null;
  const pre  = escHtml(context.slice(Math.max(0, idx - 200), idx));
  const span = `<mark>${escHtml(answer)}</mark>`;
  const post = escHtml(context.slice(idx + answer.length, idx + answer.length + 200));
  return `…${pre}${span}${post}…`;
}
