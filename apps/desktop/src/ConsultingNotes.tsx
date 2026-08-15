export interface ConsultingNote {
  summary: string;
  key_points: string[];
  risks: string[];
  assumptions: string[];
  decisions: string[];
  dependencies: string[];
  action_items: string[];
  open_questions: string[];
  message: string;
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

export function ConsultingNotesView({ notes }: { notes: ConsultingNote }) {
  return (
    <div className="setup-focus" style={{ maxHeight: "none" }}>
      <div className="setup-focus-head">
        <span className="setup-focus-title">Session Notes</span>
      </div>
      <div className="setup-focus-body">
        {notes.summary && <p className="setup-focus-line">{notes.summary}</p>}
        <ListSection label="Key Points" items={notes.key_points} />
        <ListSection label="Risks" items={notes.risks} />
        <ListSection label="Assumptions" items={notes.assumptions} />
        <ListSection label="Decisions" items={notes.decisions} />
        <ListSection label="Dependencies" items={notes.dependencies} />
        <ListSection label="Action Items" items={notes.action_items} />
        <ListSection label="Open Questions" items={notes.open_questions} />
      </div>
    </div>
  );
}
