/* background.js — service worker
 * Currently minimal — kept for future cross-tab features.
 * MV3 requires this entry even when empty. */

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(["backendUrl"], r => {
    if (!r.backendUrl) {
      chrome.storage.sync.set({ backendUrl: "http://localhost:5000" });
    }
  });
});
