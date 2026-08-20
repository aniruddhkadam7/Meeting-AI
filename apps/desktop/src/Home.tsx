interface Props {
  onSelectInterview: () => void;
  onSelectSales: () => void;
  onSelectAgents: () => void;
  onCreateAgent: () => void;
}

interface ModeDef {
  key: string;
  title: string;
  description: string;
  onClick: () => void;
}

export function Home({
  onSelectInterview,
  onSelectSales,
  onSelectAgents,
  onCreateAgent,
}: Props) {
  const modes: ModeDef[] = [
    {
      key: "interview",
      title: "Interview",
      description: "Real-time guidance that keeps you sharp when it matters most.",
      onClick: onSelectInterview,
    },
    {
      key: "agents",
      title: "Agents",
      description: "Build a custom AI agent for any role — no prompts to write.",
      onClick: onSelectAgents,
    },
    {
      key: "sales",
      title: "Sales",
      description: "Stay sharp and responsive through every customer conversation.",
      onClick: onSelectSales,
    },
  ];

  return (
    <div className="home-shell">
      <section className="home-hero">
        <div className="home-hero-text">
          <span className="home-eyebrow">Smallbird</span>
          <h1 className="home-title">Work smarter in every conversation.</h1>
          <p className="home-subtitle">
            Smallbird gives you real-time guidance and clarity during the conversations that matter —
            starting with your next interview.
          </p>
        </div>
        <div className="home-hero-actions">
          <button className="btn primary" onClick={onCreateAgent}>
            + Create Agent
          </button>
        </div>
      </section>

      <section className="home-modes">
        {modes.map((mode) => (
          <button key={mode.key} className="mode-tile primary" onClick={mode.onClick}>
            <span className="mode-tile-title">{mode.title}</span>
            <span className="mode-tile-description">{mode.description}</span>
            <span className="mode-tile-cta">Start session</span>
          </button>
        ))}
      </section>
    </div>
  );
}
