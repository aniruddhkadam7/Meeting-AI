import { useLayoutEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

const HEADER_HEIGHT = 56;
// Small gap so the dropdown reads as anchored to the header rather than
// touching it edge-to-edge — mirrors the old same-window .dropdown-menu's
// `top: calc(100% + 6px)`.
const GAP_ABOVE = 6;
// Matching gap below the dropdown's own bottom edge, so the window doesn't
// end exactly at the box's edge with zero breathing room — the resized
// window height needs to cover GAP_ABOVE + content + GAP_BELOW, not just
// GAP_ABOVE + content.
//
// This also has to cover .header-dropdown's own box-shadow
// (`0 8px 24px ...` in App.css), which paints up to 24px below the box's
// layout bottom edge without affecting scrollHeight — a shadow that size
// wasn't included here was getting clipped by the window's own bottom
// edge, since the transparent window only shows what's inside its actual
// bounds. 24 (shadow) is the dominant term; GAP_BELOW just adds a little
// past that so the shadow itself doesn't look clipped either.
const GAP_BELOW = 24 + 8;

/// Anchored dropdown/popover shell for the compact header's Mode/Context/
/// Settings/Account buttons. A Tauri webview can only paint inside its own
/// real OS window bounds, and the compact main window is a fixed 760x56
/// toolbar with no slack below the header — so this grows the actual main
/// window height to fit whatever's rendered inside it (via the Rust
/// `set_popover_content_height` command) and shrinks it back to 56px on
/// unmount.
///
/// Sizing is measure-then-resize, but the *initial* measurement is done
/// inside `useLayoutEffect` (which Chromium/WebView2 run synchronously
/// after DOM mutation but before the next paint) with the box
/// `visibility: hidden` until the first resize completes — so there's no
/// visible frame where the window is still 56px tall but the dropdown's
/// content has already painted at its full natural size. After that, a
/// ResizeObserver keeps re-measuring: several of these popovers (Account,
/// SettingsPopover's Performance sub-panel) fetch data async and change
/// height once it arrives, which a one-time initial measurement would miss
/// — leaving the window undersized and .popover-body scrolling for content
/// that would otherwise fit.
export function HeaderDropdown({
  onClose,
  children,
  className,
}: {
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  const outerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    let cancelled = false;
    // Serializes resize calls so only one is ever in flight: a
    // ResizeObserver can fire several times in quick succession while
    // multi-section content (e.g. Context's 3 upload rows) settles, and
    // those `set_popover_content_height` round-trips can resolve out of
    // order — an earlier call for a *smaller* height resolving after a
    // later call for the correct, larger one would silently shrink the
    // window back down while the DOM has already grown past it, clipping
    // the bottom of the content. Chaining each call onto the previous
    // one's promise (rather than firing them all concurrently) guarantees
    // they land in issue order, so the most recent measurement always wins.
    let chain: Promise<void> = Promise.resolve();
    const el = outerRef.current;
    if (!el) return;

    const applyHeight = () => {
      chain = chain.then(() => {
        const contentHeight = GAP_ABOVE + el.scrollHeight + GAP_BELOW;
        return invoke<void>("set_popover_content_height", { contentHeight }).catch(() => {});
      });
      return chain;
    };

    (async () => {
      await applyHeight();
      if (!cancelled) setReady(true);
    })();

    // Re-measure on later content changes (e.g. Account/SettingsPopover
    // fetch data async and change height once it arrives) — fire-and-forget
    // here is fine since the popover is already visible by this point, and
    // a brief lag while it grows to fit new content is unremarkable.
    const observer = new ResizeObserver(() => {
      applyHeight();
    });
    observer.observe(el);

    return () => {
      cancelled = true;
      observer.disconnect();
      chain = chain.then(() => invoke<void>("set_popover_content_height", { contentHeight: 0 }).catch(() => {}));
    };
  }, []);

  useLayoutEffect(() => {
    const handlePointerDown = (e: MouseEvent) => {
      if (outerRef.current && !outerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    // Capture phase so this still sees the click even if a header button's
    // own onClick (e.g. re-opening a different popover) stops propagation.
    document.addEventListener("mousedown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div
      ref={outerRef}
      className={["header-dropdown", className].filter(Boolean).join(" ")}
      style={{ top: HEADER_HEIGHT + GAP_ABOVE, visibility: ready ? "visible" : "hidden" }}
    >
      {children}
    </div>
  );
}
