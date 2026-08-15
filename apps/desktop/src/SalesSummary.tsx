import { Badge } from "./ui";

export interface SalesCallSummary {
  summary: string;
  key_requirements: string[];
  key_objections: string[];
  commitments: string[];
  action_items: string[];
  next_steps: string[];
  buying_intent: string;
  message: string;
}

function intentTone(intent: string): "success" | "warning" | "danger" | "neutral" {
  const lower = intent.toLowerCase();
  if (lower.includes("high") || lower.includes("strong")) return "success";
  if (lower.includes("low") || lower.includes("weak") || lower.includes("cold")) return "danger";
  if (lower.includes("medium") || lower.includes("moderate")) return "warning";
  return "neutral";
}

function ListSection({ label, items }: { label: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="setup-focus-group">
      <span className="setup-focus-label">{label}</span>
      <ul className="question-list large">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function SalesSummaryView({ summary }: { summary: SalesCallSummary }) {
  return (
    <div className="setup-focus" style={{ maxHeight: "none" }}>
      <div className="setup-focus-head">
        <span className="setup-focus-title">Call Summary</span>
        <Badge tone={intentTone(summary.buying_intent)}>{summary.buying_intent || "Unknown"} intent</Badge>
      </div>
      <div className="setup-focus-body">
        {summary.summary && <p className="setup-focus-line">{summary.summary}</p>}
        <ListSection label="Key Requirements" items={summary.key_requirements} />
        <ListSection label="Objections" items={summary.key_objections} />
        <ListSection label="Commitments" items={summary.commitments} />
        <ListSection label="Action Items" items={summary.action_items} />
        <ListSection label="Next Steps" items={summary.next_steps} />
      </div>
    </div>
  );
}
