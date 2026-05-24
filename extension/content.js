/* ════════════════════════════════════════════════════════════
   content.js — runs in the product page (Amazon / Flipkart)
   - Extracts product text from DOM
   - Injects floating launcher button
   - Opens sidebar iframe on demand
   ════════════════════════════════════════════════════════════ */

(function () {
  "use strict";
  if (window.__ecomqa_loaded) return;
  window.__ecomqa_loaded = true;

  // ── Site detection ──────────────────────────────────────────────────────────
  const host = location.hostname;
  const SITE = host.includes("amazon")   ? "amazon"
             : host.includes("flipkart") ? "flipkart"
             : "unknown";

  // ── Per-site DOM selectors (multiple fallbacks for resilience) ─────────────
  const SELECTORS = {
    amazon: {
      title:       ["#productTitle", "#title"],
      bullets:     ["#feature-bullets ul", "#featurebullets_feature_div"],
      description: ["#productDescription", "#aplus", "#dpx-product-description_feature_div"],
      details:     ["#productDetails_techSpec_section_1",
                    "#productDetails_detailBullets_sections1",
                    "#detailBullets_feature_div",
                    "#technicalSpecifications_feature_div"],
      reviews:     ['[data-hook="review-body"]', '#cm_cr-review_list .review-text-content'],
      qa:          ['.askInlineWidget', '#ask_lazy_load_div']
    },
    flipkart: {
      title:       ["span.B_NuCI", "h1._35KyD6", "h1.yhB1nd"],
      bullets:     ["._2418kt", "._14cfVK"],
      description: ["._1mXcCf", "._3la3Fn", "._2-N8zT"],
      details:     ["._14cfVK", "._3k-BhJ"],
      reviews:     ["._6K-7Co", ".t-ZTKy", ".ZmyHeo"],
      qa:          ["._9MgQ8H"]
    },
    unknown: {
      title:       ["h1"],
      bullets:     ["ul"],
      description: ["[itemprop='description']", "main", "article"],
      details:     [],
      reviews:     [],
      qa:          []
    }
  };

  // ── Text extraction ─────────────────────────────────────────────────────────
  function collectText(selectorList) {
    const out = [];
    for (const sel of selectorList) {
      const els = document.querySelectorAll(sel);
      els.forEach(el => {
        const t = el.innerText?.trim();
        if (t && t.length > 8) out.push(t);
      });
    }
    return out;
  }

  function extractProductText() {
    const sel    = SELECTORS[SITE];
    const parts  = [];
    const counts = {};

    for (const [section, selectors] of Object.entries(sel)) {
      const found = collectText(selectors);
      counts[section] = found.length;
      if (found.length) parts.push(`### ${section.toUpperCase()}\n${found.join("\n")}`);
    }

    const text = parts.join("\n\n").replace(/\s{3,}/g, "  ").trim();
    return { text, counts, site: SITE, url: location.href };
  }

  // ── Floating launcher button ────────────────────────────────────────────────
  function createLauncher() {
    if (document.getElementById("__ecomqa_launcher")) return;

    const btn = document.createElement("button");
    btn.id = "__ecomqa_launcher";
    btn.innerHTML = "⚡";
    btn.title = "Ask EcomQA about this product";
    Object.assign(btn.style, {
      position: "fixed", bottom: "24px", right: "24px",
      width: "56px", height: "56px", borderRadius: "50%",
      background: "linear-gradient(135deg,#6366f1,#4f46e5)",
      color: "#fff", fontSize: "26px", border: "none",
      boxShadow: "0 6px 24px rgba(79,70,229,.5)",
      cursor: "pointer", zIndex: "2147483646",
      display: "flex", alignItems: "center", justifyContent: "center",
      transition: "transform .15s, box-shadow .15s",
    });
    btn.onmouseenter = () => { btn.style.transform = "scale(1.08)"; };
    btn.onmouseleave = () => { btn.style.transform = "scale(1)"; };
    btn.onclick = openSidebar;
    document.body.appendChild(btn);
  }

  // ── Sidebar iframe ──────────────────────────────────────────────────────────
  let sidebarFrame = null;

  function openSidebar() {
    if (sidebarFrame) {
      sidebarFrame.style.transform = "translateX(0)";
      return;
    }
    sidebarFrame = document.createElement("iframe");
    sidebarFrame.id  = "__ecomqa_sidebar";
    sidebarFrame.src = chrome.runtime.getURL("sidebar.html");
    Object.assign(sidebarFrame.style, {
      position: "fixed", top: "0", right: "0",
      width: "420px", height: "100vh", border: "none",
      zIndex: "2147483647", boxShadow: "-8px 0 32px rgba(0,0,0,.4)",
      background: "#0f1117",
      transform: "translateX(100%)",
      transition: "transform .25s ease-out",
    });
    document.body.appendChild(sidebarFrame);
    requestAnimationFrame(() => {
      sidebarFrame.style.transform = "translateX(0)";
    });
  }

  // ── Listen for messages from sidebar ────────────────────────────────────────
  window.addEventListener("message", (event) => {
    if (event.source !== sidebarFrame?.contentWindow) return;
    const msg = event.data;
    if (!msg || msg.from !== "ecomqa_sidebar") return;

    if (msg.action === "get_product") {
      const data = extractProductText();
      sidebarFrame.contentWindow.postMessage(
        { from: "ecomqa_content", action: "product_data", data }, "*"
      );
    } else if (msg.action === "close") {
      sidebarFrame.style.transform = "translateX(100%)";
      setTimeout(() => {
        if (sidebarFrame) { sidebarFrame.remove(); sidebarFrame = null; }
      }, 250);
    }
  });

  // ── Init ────────────────────────────────────────────────────────────────────
  function isProductPage() {
    if (SITE === "amazon")   return /\/(dp|gp\/product)\//.test(location.pathname);
    if (SITE === "flipkart") return /\/p\//.test(location.pathname);
    return false;
  }

  if (isProductPage()) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", createLauncher);
    } else {
      createLauncher();
    }
  }
})();
