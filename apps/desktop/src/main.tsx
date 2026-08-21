import React from "react";
import ReactDOM from "react-dom/client";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import App from "./App";
import { InterviewOverlay } from "./InterviewOverlay";
import { MeetingOverlay } from "./MeetingOverlay";
import "./tailwind.css";
import "./overlay.css";

// The overlay windows load the exact same index.html/bundle as the main
// window (Tauri's WebviewUrl::App points both at "index.html") — which root
// component renders is decided here by the window's label, set when each
// overlay is created in Rust.
const FIXED_OVERLAY_LABELS = new Set(["interview-overlay", "meeting-overlay"]);

const label = getCurrentWebviewWindow().label;
const isOverlay = FIXED_OVERLAY_LABELS.has(label);
if (isOverlay) {
  document.body.classList.add("overlay-window");
  // Also mark <html>. Vite bundles every stylesheet into one file regardless
  // of which component imported it, so App.css's `html, body { background }`
  // rule reaches this window too and would paint an opaque canvas behind the
  // overlay — defeating the window's transparency. Marking the root element
  // lets overlay.css override it by specificity, without depending on CSS
  // `:has()` support in whatever WebView2 version is installed.
  document.documentElement.classList.add("overlay-window");
}

function Root() {
  if (label === "interview-overlay") return <InterviewOverlay />;
  if (label === "meeting-overlay") return <MeetingOverlay />;
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
