# EcomQA Chrome Extension

Floating "Ask" button on Amazon and Flipkart pages. Click it, ask anything about the product, get BERT-powered answers + sentiment analysis. No more scraping — text is read straight from the page DOM.

---

## Install (1 minute)

### 1. Update your backend

The extension needs a CORS-enabled endpoint. If you already pulled the latest code:

```powershell
pip install flask-cors
python -m src.app
```

Backend should be running on `http://localhost:5000`.

### 2. Load the extension in Chrome

1. Open `chrome://extensions/`
2. Toggle **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension/` folder
5. The ⚡ icon appears in your toolbar — pin it for easy access

### 3. Test it

1. Open any Amazon product page (e.g. `https://www.amazon.in/dp/...`)
2. A floating purple ⚡ button appears bottom-right
3. Click it → sidebar slides open
4. Ask: *"What is the battery life?"* or click a quick-prompt chip
5. Answer appears with confidence score

---

## When you deploy the backend

1. Get your hosted URL (e.g. `https://your-name-ecom-qa-bert.hf.space`)
2. Click the ⚡ icon in Chrome toolbar
3. Paste the URL in **Backend URL** field
4. Click **Save & Test** — green ✓ means connected

---

## What the extension does differently

- ✅ **No scraping** — reads text directly from the loaded page DOM (no bot detection, no CAPTCHAs)
- ✅ **Includes reviews + Q&A** — extracts everything visible on the page
- ✅ **Works on logged-in pages** — sees content only logged-in users see
- ✅ **No history saved** (anonymous endpoint) — privacy-friendly
- ✅ **Multi-site** — Amazon (.com, .in, .co.uk, .de, .ca, .com.au) + Flipkart

---

## Files

| File | Purpose |
|------|---------|
| `manifest.json` | Extension config (MV3) |
| `content.js` | Runs in product page — extracts text, injects button |
| `sidebar.html/js/css` | The sidebar UI |
| `popup.html/js` | Toolbar icon settings (backend URL) |
| `background.js` | Service worker |
| `icons/` | Toolbar icons |

---

## Publish to Chrome Web Store (optional)

1. Pay $5 one-time developer fee at https://chrome.google.com/webstore/devconsole
2. Zip the `extension/` folder (without the parent directory)
3. Upload → fill in description, screenshots → submit for review
4. Approval: 1–3 days

---

## Troubleshooting

**Floating button doesn't appear?** Check:
- URL contains `/dp/` (Amazon) or `/p/` (Flipkart)
- Refresh the page after enabling the extension
- Check console (F12) for errors

**"Cannot reach backend" in popup?** Check:
- Backend is running (`python -m src.app`)
- URL has no trailing slash
- CORS is enabled (latest backend code)

**Empty results?** Check:
- Product page actually has content loaded
- Open browser DevTools → Network tab → see the `/api/extension/ask` call
