/* popup.js — settings panel logic */

const input   = document.getElementById("backendUrl");
const saveBtn = document.getElementById("saveBtn");
const status  = document.getElementById("status");

// Load existing setting
chrome.storage.sync.get(["backendUrl"], r => {
  input.value = r.backendUrl || "http://localhost:5000";
});

saveBtn.addEventListener("click", async () => {
  let url = input.value.trim().replace(/\/+$/, "");
  if (!url) return;

  // Test connection
  status.className = "status";
  status.textContent = "Testing connection…";
  status.style.display = "block";

  try {
    const res = await fetch(url + "/", { method: "GET" });
    if (res.ok) {
      chrome.storage.sync.set({ backendUrl: url }, () => {
        status.className = "status ok";
        status.textContent = "✓ Connected. Settings saved.";
      });
    } else {
      throw new Error("HTTP " + res.status);
    }
  } catch (e) {
    status.className = "status err";
    status.textContent = "✗ Cannot reach backend: " + e.message;
  }
});
