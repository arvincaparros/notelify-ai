// Service worker -- lifecycle and session coordinator (docs/06, "Service
// Worker" section). Phase 0 skeleton only: no offscreen-document lifecycle
// management, no auth/token coordination, no message handlers yet. It is
// never assumed to stay alive -- nothing here relies on in-memory state
// surviving a restart, consistent with the approved design from the start.

console.log("[Notelify AI] service worker loaded (Phase 0 skeleton)");

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Notelify AI] installed");
});
