// Offscreen document -- owns all capture and upload execution (docs/06,
// "Offscreen Document" section). Phase 0 skeleton only: no MediaRecorder,
// no getUserMedia/tabCapture, no chunk upload, no IndexedDB wiring, no
// GET_ACCESS_TOKEN message handling yet. Not created by the service worker
// yet either -- this file exists so the planned entry point is in place,
// per the approved spec's structure, not because it's reachable today.

console.log("[Notelify AI] offscreen document loaded (Phase 0 skeleton)");
