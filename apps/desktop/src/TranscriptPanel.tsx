import { useEffect, useRef } from "react";
import type { TranscriptSegment } from "./types";
import { EmptyState } from "./ui";

function formatElapsed(startedAtMs: number, timestampMs: number) {
  const deltaMs = Math.max(0, timestampMs - startedAtMs);
  const totalSeconds = Math.floor(deltaMs / 1000);
  const mm = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const ss = (totalSeconds % 60).toString().padStart(2, "0");
  return `${mm}:${ss}`;
}

interface Props {
  segments: TranscriptSegment[];
  livePartial: string;
  sessionStartedAtMs: number;
  autoScroll: boolean;
}

export function TranscriptPanel({
  segments,
  livePartial,
  sessionStartedAtMs,
  autoScroll,
}: Props) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (autoScroll) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [segments.length, livePartial, autoScroll]);

  return (
    <section className="transcript-panel">
      <div className="transcript-panel-header">
        <span>Interview Transcript</span>
        {autoScroll && (
          <span className="transcript-panel-live">
            <span className="status-dot danger pulse" />
            Live
          </span>
        )}
      </div>
      <div className="transcript-panel-body" ref={bodyRef}>
        {segments.length === 0 && !livePartial && (
          <EmptyState
            icon="💬"
            title="No transcript yet"
            description="Start recording and your conversation will appear here as it happens."
          />
        )}
        {segments.map((seg) => (
          <div className="transcript-entry" key={seg.id}>
            <div className="transcript-entry-time">
              {formatElapsed(sessionStartedAtMs, seg.timestamp)}
            </div>
            <div className="transcript-entry-text">{seg.final_text}</div>
          </div>
        ))}
        {livePartial && (
          <div className="transcript-entry partial" key="live-partial">
            <div className="transcript-entry-time">live</div>
            <div className="transcript-entry-text">{livePartial}</div>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}
