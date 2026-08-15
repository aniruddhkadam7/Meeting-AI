import { useState } from "react";
import type { OverallInterviewAnalysis, QuestionAnalysis } from "./types";
import { Badge, Button, Card, EmptyState } from "./ui";

const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  completed: "success",
  partial: "warning",
  failed: "danger",
};

type ResultsTab = "OVERVIEW" | "QUESTIONS" | "STRENGTHS" | "WEAKNESSES";

interface Props {
  result: OverallInterviewAnalysis;
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      <span className="score-value">{score}</span>
    </div>
  );
}

function QuestionCard({ qa }: { qa: QuestionAnalysis }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(qa.improved_answer);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable; silently ignore, the answer is still
      // visible on screen to copy manually.
    }
  };

  if (qa.failed) {
    return (
      <div className="question-card question-card-failed">
        <p className="question-text">{qa.question}</p>
        <p className="error">Question analysis failed{qa.error_message ? `: ${qa.error_message}` : "."}</p>
      </div>
    );
  }

  return (
    <div className="question-card">
      <div className="question-card-header">
        <p className="question-text">{qa.question}</p>
        <span className="question-score">{qa.score}</span>
      </div>

      <div className="question-section">
        <span className="question-section-label">Your Answer</span>
        <p className="question-section-body">{qa.candidate_answer || "(No answer captured)"}</p>
      </div>

      <div className="question-section">
        <span className="question-section-label">Assessment</span>
        <p className="question-section-body">{qa.assessment}</p>
      </div>

      {qa.strengths.length > 0 && (
        <div className="question-section">
          <span className="question-section-label">Strengths</span>
          <ul className="question-list">
            {qa.strengths.map((s, i) => (
              <li key={i}>✓ {s}</li>
            ))}
          </ul>
        </div>
      )}

      {qa.issues.length > 0 && (
        <div className="question-section">
          <span className="question-section-label">Could Improve</span>
          <ul className="question-list">
            {qa.issues.map((s, i) => (
              <li key={i}>⚠ {s}</li>
            ))}
          </ul>
        </div>
      )}

      {qa.improved_answer && (
        <div className="question-section">
          <span className="question-section-label">Improved Answer</span>
          <p className="question-section-body improved-answer">{qa.improved_answer}</p>
          <Button variant="secondary" size="sm" onClick={copyAnswer}>
            {copied ? "Copied!" : "Copy Answer"}
          </Button>
        </div>
      )}

      {qa.retrieved_sources.length > 0 && (
        <div className="question-section">
          <button className="link-button" onClick={() => setSourcesOpen((v) => !v)}>
            {sourcesOpen ? "Hide" : "Show"} Sources ({qa.retrieved_sources.length})
          </button>
          {sourcesOpen && (
            <div className="sources-list">
              {qa.retrieved_sources.map((src, i) => (
                <div className="source-item" key={i}>
                  <div className="source-item-header">
                    <span>{src.filename}</span>
                    <span className="source-item-score">{src.score.toFixed(2)}</span>
                  </div>
                  <p className="source-item-text">{src.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ResultsDashboard({ result }: Props) {
  const [tab, setTab] = useState<ResultsTab>("OVERVIEW");

  return (
    <Card className="results-dashboard">
      <div className="results-header">
        <h2>Interview Analysis</h2>
        <Badge tone={STATUS_TONE[result.status] ?? "neutral"}>{result.status}</Badge>
      </div>
      <p className="ai-disclaimer">{result.disclaimer}</p>
      {result.message && <p className="hint small">{result.message}</p>}

      <nav className="results-tab-bar">
        {(["OVERVIEW", "QUESTIONS", "STRENGTHS", "WEAKNESSES"] as ResultsTab[]).map((t) => (
          <button
            key={t}
            className={`results-tab-button ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0) + t.slice(1).toLowerCase()}
            {t === "QUESTIONS" && result.questions.length > 0 ? ` (${result.questions.length})` : ""}
          </button>
        ))}
      </nav>

      {tab === "OVERVIEW" && (
        <div className="results-tab-content">
          <div className="overall-score-display">
            <span className="overall-score-value">{result.overall_score}</span>
            <span className="overall-score-max">/100</span>
          </div>
          {result.summary && <p className="overview-summary">{result.summary}</p>}
          <div className="score-breakdown">
            <ScoreBar label="Technical Knowledge" score={result.technical_score} />
            <ScoreBar label="Communication" score={result.communication_score} />
            <ScoreBar label="Practical Experience" score={result.practical_experience_score} />
            <ScoreBar label="Confidence" score={result.confidence_score} />
          </div>
          {result.recommendations.length > 0 && (
            <div className="question-section">
              <span className="question-section-label">Recommendations</span>
              <ul className="question-list">
                {result.recommendations.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {tab === "QUESTIONS" && (
        <div className="results-tab-content questions-tab">
          {result.questions.length === 0 ? (
            <EmptyState icon="❓" title="No questions identified" description="No interview questions were detected in the transcript." />
          ) : (
            result.questions.map((qa) => <QuestionCard qa={qa} key={qa.question_id} />)
          )}
        </div>
      )}

      {tab === "STRENGTHS" && (
        <div className="results-tab-content">
          {result.strengths.length === 0 ? (
            <EmptyState icon="✓" title="No strengths identified" />
          ) : (
            <ul className="question-list large">
              {result.strengths.map((s, i) => (
                <li key={i}>✓ {s}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "WEAKNESSES" && (
        <div className="results-tab-content">
          {result.weaknesses.length === 0 ? (
            <EmptyState icon="⚠" title="No areas to improve identified" />
          ) : (
            <ul className="question-list large">
              {result.weaknesses.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
