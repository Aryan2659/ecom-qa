/* ════════════════════════════════════════════════════════════
   sidebar.js — handles Ask + Compare tabs
   ════════════════════════════════════════════════════════════ */

"use strict";

const $ = id => document.getElementById(id);

let productData    = null;
let backendBaseUrl = "http://localhost:5000";
let savedProducts  = [];

// ── Load settings ────────────────────────────────────────────────────────────
chrome.storage.sync.get(["backendUrl"], r => {
  if (r.backendUrl) backendBaseUrl = r.backendUrl;
  $("backendUrl").textContent = backendBaseUrl;
  checkBackendHealth();
});

chrome.storage.local.get(["savedProducts"], r => {
  savedProducts = Array.isArray(r.savedProducts) ? r.savedProducts : [];
  renderSavedList();
});

async function checkBackendHealth() {
  try {
    const r = await fetch(backendBaseUrl + "/");
    setBackendStatus(r.ok);
  } catch { setBackendStatus(false); }
}
function setBackendStatus(ok) {
  const el = $("backendStatus");
  el.style.color = ok ? "#22c55e" : "#ef4444";
  el.title = ok ? "Backend reachable" : "Backend unreachable";
}

// ── Tab switching ────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $("pane-" + btn.dataset.tab).classList.add("active");
  });
});

// ── Request product text from content script ────────────────────────────────
function requestProductText() {
  window.parent.postMessage({ from: "ecomqa_sidebar", action: "get_product" }, "*");
}

window.addEventListener("message", (event) => {
  const msg = event.data;
  if (!msg || msg.from !== "ecomqa_content") return;
  if (msg.action === "product_data") {
    productData = msg.data;
    renderProductStatus();
  }
});

function renderProductStatus() {
  const dot = $("statusDot"), text = $("statusText");
  if (!productData?.text) {
    dot.style.background = "#ef4444";
    text.textContent = "No product text detected on this page";
    return;
  }
  const chars   = productData.text.length;
  const reviewN = productData.counts?.reviews || 0;
  dot.style.background = "#22c55e";
  text.innerHTML = `<strong>${productData.site.toUpperCase()}</strong> · ${chars.toLocaleString()} chars · ${reviewN} reviews`;
  $("askBtn").disabled = false;
  $("saveProductBtn").disabled = false;
}

// ── Close ────────────────────────────────────────────────────────────────────
$("closeBtn").addEventListener("click", () => {
  window.parent.postMessage({ from: "ecomqa_sidebar", action: "close" }, "*");
});

// ── ASK ──────────────────────────────────────────────────────────────────────
$("askBtn").addEventListener("click", handleAsk);
$("questionInput").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAsk(); }
});
document.querySelectorAll(".chip").forEach(c => {
  c.addEventListener("click", () => { $("questionInput").value = c.dataset.q; handleAsk(); });
});

async function handleAsk() {
  const q = $("questionInput").value.trim();
  if (!q || !productData?.text) return;
  prependAnswerCard("answerContainer", { question: q, loading: true });
  try {
    const r = await fetch(backendBaseUrl + "/api/extension/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, context: productData.text })
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    updateAnswerCard("answerContainer", q, data);
  } catch (e) {
    updateAnswerCard("answerContainer", q, null, e.message);
  }
}

// ── SAVE PRODUCT ─────────────────────────────────────────────────────────────
$("saveProductBtn").addEventListener("click", () => {
  if (!productData?.text) return;
  // Extract title from text (first line of "### TITLE")
  const titleMatch = productData.text.match(/### TITLE\s*\n(.+)/);
  const name = titleMatch ? titleMatch[1].slice(0, 80) : productData.url.slice(0, 60);

  // Avoid duplicates by URL
  if (savedProducts.some(p => p.url === productData.url)) {
    flashSaveBtn("Already saved ✓");
    return;
  }
  if (savedProducts.length >= 4) {
    flashSaveBtn("Max 4 products");
    return;
  }
  savedProducts.push({
    name, url: productData.url, site: productData.site,
    text: productData.text, savedAt: Date.now()
  });
  chrome.storage.local.set({ savedProducts });
  renderSavedList();
  flashSaveBtn("Saved ✓");
});

function flashSaveBtn(msg) {
  const btn = $("saveProductBtn");
  const orig = btn.textContent;
  btn.textContent = msg;
  btn.disabled = true;
  setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1200);
}

// ── SAVED LIST UI ────────────────────────────────────────────────────────────
function renderSavedList() {
  $("savedBadge").textContent = savedProducts.length;
  const list = $("savedList");
  if (savedProducts.length === 0) {
    list.innerHTML = `<div class="empty-msg">No products saved yet. Go to a product page, click "Save for comparison".</div>`;
    $("compareBtn").disabled = true;
    return;
  }
  list.innerHTML = savedProducts.map((p, i) => `
    <div class="saved-item">
      <div class="saved-info">
        <div class="saved-name">${escHtml(p.name)}</div>
        <div class="saved-site">${p.site.toUpperCase()} · ${p.text.length.toLocaleString()} chars</div>
      </div>
      <button class="icon-btn remove-saved" data-idx="${i}" title="Remove">✕</button>
    </div>`).join("");

  list.querySelectorAll(".remove-saved").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = +btn.dataset.idx;
      savedProducts.splice(idx, 1);
      chrome.storage.local.set({ savedProducts });
      renderSavedList();
    });
  });
  $("compareBtn").disabled = savedProducts.length < 2;
}

$("clearAllBtn").addEventListener("click", () => {
  if (!confirm("Remove all saved products?")) return;
  savedProducts = [];
  chrome.storage.local.set({ savedProducts });
  renderSavedList();
  $("compareResults").innerHTML = "";
});

// ── COMPARE ──────────────────────────────────────────────────────────────────
$("compareBtn").addEventListener("click", handleCompare);
$("compareQuestion").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleCompare(); }
});

async function handleCompare() {
  const q = $("compareQuestion").value.trim();
  if (!q || savedProducts.length < 2) return;

  $("compareResults").innerHTML = `
    <div class="loading-row"><div class="spinner-sm"></div>
    <span>Running BERT on ${savedProducts.length} products…</span></div>`;

  try {
    const r = await fetch(backendBaseUrl + "/api/extension/compare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: q,
        products: savedProducts.map(p => ({ name: p.name, url: p.url, text: p.text }))
      })
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    renderComparison(data);
  } catch (e) {
    $("compareResults").innerHTML = `<div class="error-box">⚠ ${escHtml(e.message)}</div>`;
  }
}

function renderComparison(data) {
  let html = "";

  if (data.winner?.url) {
    const idx = data.products.findIndex(p => p.url === data.winner.url);
    html += `<div class="winner-banner">🏆 Best match: <strong>${escHtml(data.products[idx].name)}</strong> (score ${data.winner.score})</div>`;
  }

  html += data.products.map((p, i) => {
    const isWinner = data.winner?.url === p.url;
    let body = "";
    if (p.error) {
      body = `<div class="error-box">⚠ ${escHtml(p.error)}</div>`;
    } else {
      if (p.qa) {
        const c = p.qa.confidence_score || 0;
        const k = c >= 0.7 ? "high" : c >= 0.4 ? "medium" : "low";
        body += `
          <div class="compare-answer">${escHtml(p.qa.answer)}</div>
          <div class="badge-row">
            <span class="badge badge-${k}">${p.qa.confidence_label} (${Math.round(c*100)}%)</span>
            <span class="badge badge-source">${p.qa.source}</span>
          </div>`;
      }
      if (p.sentiment) {
        const stars = Math.round(p.sentiment.average_stars);
        body += `<div class="compare-sentiment">
          <span class="sentiment-stars-sm">${"★".repeat(stars)}${"☆".repeat(5-stars)}</span>
          <span>${p.sentiment.average_stars}/5 · ${p.sentiment.overall_sentiment}</span>
        </div>`;
      }
    }
    return `
      <div class="compare-card ${isWinner ? 'winner' : ''}">
        <div class="compare-card-header">
          <span class="compare-num">#${i+1}</span>
          <span class="compare-name">${escHtml(p.name)}</span>
          ${isWinner ? '<span class="winner-pill">🏆</span>' : ''}
        </div>
        ${body}
      </div>`;
  }).join("");

  html += `<div class="meta-line">Intent: <strong>${data.intent}</strong></div>`;
  $("compareResults").innerHTML = html;
}

// ── Rendering helpers ────────────────────────────────────────────────────────
let cardCounter = 0;

function prependAnswerCard(containerId, { question, loading }) {
  const id = "card_" + (++cardCounter);
  const html = `
    <div class="answer-card" id="${id}" data-question="${escHtml(question)}">
      <div class="qa-question">${escHtml(question)}</div>
      ${loading ? `<div class="loading-row"><div class="spinner-sm"></div><span>Analysing…</span></div>` : ""}
    </div>`;
  $(containerId).insertAdjacentHTML("afterbegin", html);
}

function updateAnswerCard(containerId, question, data, error) {
  const card = [...document.querySelectorAll(`#${containerId} .answer-card`)]
    .find(c => c.dataset.question === escHtml(question) && c.querySelector(".loading-row"));
  if (!card) return;

  let body = "";
  if (error) {
    body = `<div class="error-box">⚠ ${escHtml(error)}</div>`;
  } else {
    if (data.qa) {
      const c = data.qa.confidence_score || 0;
      const k = c >= 0.7 ? "high" : c >= 0.4 ? "medium" : "low";
      body += `
        <div class="qa-answer">${escHtml(data.qa.answer)}</div>
        <div class="badge-row">
          <span class="badge badge-${k}">${data.qa.confidence_label} (${Math.round(c*100)}%)</span>
          <span class="badge badge-source">${data.qa.source}</span>
        </div>`;
    }
    if (data.sentiment) {
      const stars = Math.round(data.sentiment.average_stars);
      body += `<div class="sentiment-block">
        <div class="sentiment-stars">${"★".repeat(stars)}${"☆".repeat(5-stars)}
          <span class="sentiment-num">${data.sentiment.average_stars}/5</span></div>
        <div class="sentiment-summary">${escHtml(data.sentiment.overall_sentiment)} · ${data.sentiment.sentences_analysed} sentences</div>
      </div>`;
    }
    body += `<div class="meta-line">Intent: <strong>${data.intent}</strong></div>`;
  }
  card.querySelector(".loading-row").outerHTML = body;
}

function escHtml(s) {
  return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── Boot ─────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  setTimeout(requestProductText, 100);
});
