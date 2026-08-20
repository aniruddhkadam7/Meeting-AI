import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import {
  answerStyleToOverlayFields,
  loadOverlaySettings,
  saveOverlaySettings,
  type AnswerStyle,
  type EnglishLevel,
  type Humanization,
} from "./overlaySettings";
import type { DocumentType } from "./types";
import { Button, Spinner } from "./ui";

interface Props {
  onStart: () => void;
}

interface SectionConfig {
  key: string;
  documentType: DocumentType;
  label: string;
  placeholder: string;
  textareaPlaceholder: string;
}

const SECTIONS: SectionConfig[] = [
  {
    key: "resume",
    documentType: "RESUME",
    label: "CV / Resume",
    placeholder: "Upload a file",
    textareaPlaceholder: "Or paste your resume text here",
  },
  {
    key: "job_description",
    documentType: "JOB_DESCRIPTION",
    label: "Job Description",
    placeholder: "Upload a file",
    textareaPlaceholder: "Or paste the job description here",
  },
  {
    key: "context",
    documentType: "INTERVIEW_PREPARATION",
    label: "Additional Context",
    placeholder: "Upload a file",
    textareaPlaceholder: "Projects, company information, notes, portfolio, or anything else worth knowing",
  },
];

type SectionState = {
  fileName: string | null;
  fileBytes: number[] | null;
  text: string;
  uploading: boolean;
  /// Set once this section's file has been uploaded to the RAG service (for
  /// resume/job_description this happens right away, on pick, rather than
  /// waiting for Start Interview — see `pickFile` — so its extracted text can
  /// be polled for the auto-analysis summary). Start Interview skips
  /// re-uploading a section that already has one.
  documentId: string | null;
};

const EMPTY_SECTION: SectionState = {
  fileName: null,
  fileBytes: null,
  text: "",
  uploading: false,
  documentId: null,
};

interface SetupAnalysisResponse {
  job_title: string | null;
  company: string | null;
  seniority: string | null;
  employment_type: string | null;
  key_responsibilities: string[];
  required_skills: string[];
  technologies: string[];
  focus_areas: string[];
  candidate_highlights: string[];
}

function hasFocusContent(focus: SetupAnalysisResponse): boolean {
  return Boolean(
    focus.job_title ||
      focus.company ||
      focus.seniority ||
      focus.employment_type ||
      focus.key_responsibilities.length ||
      focus.required_skills.length ||
      focus.technologies.length ||
      focus.focus_areas.length ||
      focus.candidate_highlights.length,
  );
}

// Plain-text-ish files can be read for auto-analysis directly in the
// browser. PDF/DOCX are opaque bytes here, so for those we upload
// immediately on pick and poll the RAG service for the text it already
// extracts as part of its normal processing pipeline (see
// `pollForExtractedText` below) rather than re-implementing PDF/DOCX parsing
// on the desktop side.
const TEXT_EXTENSIONS = [".txt", ".md", ".markdown"];
const SERVER_PARSED_EXTENSIONS = [".pdf", ".docx"];

function isTextFile(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return TEXT_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function needsServerExtraction(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return SERVER_PARSED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

const ANALYSIS_DEBOUNCE_MS = 800;
const EXTRACTION_POLL_INTERVAL_MS = 1200;
const EXTRACTION_POLL_TIMEOUT_MS = 30_000;

export function InterviewSetup({ onStart }: Props) {
  const [sections, setSections] = useState<Record<string, SectionState>>(() =>
    Object.fromEntries(SECTIONS.map((s) => [s.key, { ...EMPTY_SECTION }])),
  );
  const [role, setRole] = useState("");
  const [company, setCompany] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Decoded text for uploaded .txt/.md files, keyed by section — separate
  // from `sections[key].text` (which is only the pasted-text textarea) so a
  // file upload and a paste never fight over the same field. Only used to
  // feed the auto-analysis call.
  const [uploadedText, setUploadedText] = useState<Record<string, string>>({});
  const [focusSummary, setFocusSummary] = useState<SetupAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [englishLevel, setEnglishLevel] = useState<EnglishLevel>(
    () => loadOverlaySettings().englishLevel,
  );
  const [answerStyle, setAnswerStyle] = useState<AnswerStyle>(
    () => loadOverlaySettings().answerStyle,
  );
  const [humanization, setHumanization] = useState<Humanization>(
    () => loadOverlaySettings().humanization,
  );
  const [styleOpen, setStyleOpen] = useState(false);
  const analysisSeq = useRef(0);
  // Tracks whether the user has typed into Role/Company themselves, so the
  // auto-fill from JD analysis only ever fills an empty field and never
  // overwrites something the user deliberately entered or edited.
  const roleTouched = useRef(false);
  const companyTouched = useRef(false);

  // Prewarms the STT sidecar the moment this screen mounts, rather than
  // waiting for Start Interview to be clicked. `start_system_audio_capture`
  // blocks until the ASR model has fully loaded — typically several seconds,
  // more on slower hardware (see commands.rs's start_capture_inner and
  // stt/sidecar.rs's SttSidecar::spawn) — so kicking it off here lets that
  // load overlap with the user filling in role/company and uploading
  // documents. By the time Start Interview is actually clicked, capture is
  // usually already warm and the overlay opens already listening in real
  // time instead of the click itself eating the full load time.
  //
  // `startInterview` below awaits this exact promise rather than issuing a
  // fresh `start_system_audio_capture` call, since a second concurrent call
  // while this one is still mid-load would just get "capture already
  // running" back immediately — true once the session reaches Recording, but
  // also returned while it's still Starting, which would make Start
  // Interview proceed to show the overlay before capture is actually ready.
  const prewarmRef = useRef<Promise<void> | null>(null);
  useEffect(() => {
    const promise = invoke<void>("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") throw e;
    });
    prewarmRef.current = promise;
    // Nothing awaits this while the user is still on the setup screen — swallow
    // here so a genuine failure doesn't surface as an unhandled rejection.
    // startInterview() awaits the same promise and reports the same error
    // there if it's still failing once the user actually clicks Start.
    promise.catch(() => {});
  }, []);

  const handleRoleChange = useCallback((value: string) => {
    roleTouched.current = true;
    setRole(value);
  }, []);

  const handleCompanyChange = useCallback((value: string) => {
    companyTouched.current = true;
    setCompany(value);
  }, []);

  // Polls get_document_text until the RAG service finishes extracting text
  // for a just-uploaded document (or gives up after ~30s — extraction is
  // normally a couple seconds; this is only a ceiling so a stuck/unreachable
  // RAG service can't spin the setup page forever).
  const pollForExtractedText = useCallback(async (key: string, documentId: string) => {
    const deadline = Date.now() + EXTRACTION_POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        const text = await invoke<string | null>("get_document_text", { documentId });
        if (text) {
          setUploadedText((prev) => ({ ...prev, [key]: text }));
          return;
        }
      } catch {
        // RAG service unavailable or the document errored out — stop polling
        // silently, the setup page stays fully usable without the summary.
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, EXTRACTION_POLL_INTERVAL_MS));
    }
  }, []);

  const pickFile = useCallback(
    async (key: string) => {
      setError(null);
      try {
        const selected = await open({
          multiple: false,
          filters: [{ name: "Documents", extensions: ["pdf", "docx", "txt", "md", "markdown"] }],
        });
        if (!selected || Array.isArray(selected)) return;
        const bytes = await readFile(selected);
        const fileName = selected.split(/[\\/]/).pop() ?? "document";
        setSections((prev) => ({
          ...prev,
          [key]: { ...prev[key], fileName, fileBytes: Array.from(bytes), text: "", documentId: null },
        }));
        setUploadedText((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });

        if (isTextFile(fileName)) {
          setUploadedText((prev) => ({ ...prev, [key]: new TextDecoder().decode(bytes) }));
          return;
        }

        // PDF/DOCX: only resume and job_description feed the auto-analysis
        // summary, so only upload those two immediately. "Additional
        // Context" still uploads at Start Interview as before (it's not part
        // of the summary).
        const section = SECTIONS.find((s) => s.key === key);
        if (!section || (key !== "resume" && key !== "job_description")) return;
        if (!needsServerExtraction(fileName)) return;

        try {
          const metadata = await invoke<{ document_id: string }>("upload_document", {
            filename: fileName,
            bytes: Array.from(bytes),
            documentType: section.documentType,
          });
          setSections((prev) => ({
            ...prev,
            [key]: { ...prev[key], documentId: metadata.document_id },
          }));
          pollForExtractedText(key, metadata.document_id);
        } catch {
          // Upload failed — Start Interview will retry it; the summary
          // simply won't include this document.
        }
      } catch (e) {
        setError(String(e));
      }
    },
    [pollForExtractedText],
  );

  const clearFile = useCallback((key: string) => {
    setSections((prev) => ({
      ...prev,
      [key]: { ...prev[key], fileName: null, fileBytes: null, documentId: null },
    }));
    setUploadedText((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const setText = useCallback((key: string, text: string) => {
    setSections((prev) => ({ ...prev, [key]: { ...prev[key], text, fileName: null, fileBytes: null } }));
    setUploadedText((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const resumeSource = sections.resume.text.trim() || uploadedText.resume || "";
  const jdSource = sections.job_description.text.trim() || uploadedText.job_description || "";

  // Debounced auto-analysis: re-runs whenever the resume or job-description
  // text changes (paste or a .txt/.md upload), skipped entirely for empty
  // input or PDF/DOCX uploads (no text available client-side for those).
  useEffect(() => {
    if (!resumeSource.trim() && !jdSource.trim()) {
      setFocusSummary(null);
      setAnalyzing(false);
      return;
    }
    const seq = ++analysisSeq.current;
    const timer = setTimeout(async () => {
      setAnalyzing(true);
      try {
        const result = await invoke<SetupAnalysisResponse>("analyze_setup_context", {
          resumeText: resumeSource.trim() || null,
          jobDescriptionText: jdSource.trim() || null,
        });
        if (seq === analysisSeq.current) {
          setFocusSummary(hasFocusContent(result) ? result : null);
          // Auto-fill Role/Company from what the JD/resume analysis
          // detected — but only into a field the user hasn't touched, so a
          // deliberately typed or edited value is never overwritten.
          if (result.job_title && !roleTouched.current) setRole(result.job_title);
          if (result.company && !companyTouched.current) setCompany(result.company);
        }
      } catch {
        // Best-effort — the setup page remains fully usable without the
        // summary; there is nothing actionable to show the user here.
        if (seq === analysisSeq.current) setFocusSummary(null);
      } finally {
        if (seq === analysisSeq.current) setAnalyzing(false);
      }
    }, ANALYSIS_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [resumeSource, jdSource]);

  const startInterview = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      // Every Start Interview begins a fresh session: role/company are
      // whatever was just typed here (never carried over from a previous
      // interview), written into the overlay's own settings store so both
      // the ASK AI flow and history archiving can read them.
      const overlaySettings = loadOverlaySettings();
      saveOverlaySettings({
        ...overlaySettings,
        role: role.trim(),
        company: company.trim(),
        englishLevel,
        answerStyle,
        humanization,
        ...answerStyleToOverlayFields(answerStyle),
      });

      // Fire document uploads without waiting for parsing/chunking/embedding to
      // finish — the overlay's RAG search already tolerates documents becoming
      // searchable a few seconds after upload, so blocking Start Interview on
      // that pipeline just makes the button feel slow for no benefit.
      for (const section of SECTIONS) {
        const state = sections[section.key];
        if (state.documentId) {
          // Already uploaded eagerly on pick (resume/job_description
          // PDF/DOCX, for the auto-analysis summary) — don't upload twice.
          continue;
        }
        if (state.fileBytes && state.fileName) {
          invoke("upload_document", {
            filename: state.fileName,
            bytes: state.fileBytes,
            documentType: section.documentType,
          }).catch((e) => console.error(`Failed to upload ${section.label}:`, e));
        } else if (state.text.trim()) {
          const bytes = Array.from(new TextEncoder().encode(state.text.trim()));
          invoke("upload_document", {
            filename: `${section.key}.txt`,
            bytes,
            documentType: section.documentType,
          }).catch((e) => console.error(`Failed to upload ${section.label}:`, e));
        }
      }
      // Wait on the prewarm kicked off when this screen mounted (usually
      // already resolved by now) rather than invoking
      // start_system_audio_capture again — see the comment on prewarmRef.
      // Falls back to a fresh call only if the mount effect somehow hasn't
      // run yet (e.g. an extremely fast click).
      await (prewarmRef.current ??
        invoke("start_system_audio_capture").catch((e) => {
          if (String(e) !== "capture already running") throw e;
        }));
      await invoke("show_interview_overlay");
      onStart();
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  }, [sections, onStart, role, company, englishLevel, answerStyle, humanization]);

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">New Interview</h1>
          <p className="setup-subtitle">Set up context, then start your session</p>
        </div>

        <div className="setup-hero-actions">
          <div className="setup-style-anchor">
            <button
              type="button"
              className="setup-style-toggle"
              onClick={() => setStyleOpen((v) => !v)}
            >
              <span>Answer Style</span>
              <span className="setup-style-caret">{styleOpen ? "▲" : "▼"}</span>
            </button>
            {styleOpen && (
              <div className="setup-style-popover">
                <div className="setup-style-field">
                  <label htmlFor="setup-english-level">English</label>
                  <select
                    id="setup-english-level"
                    className="setup-input"
                    value={englishLevel}
                    onChange={(e) => setEnglishLevel(e.target.value as EnglishLevel)}
                  >
                    <option value="simple">Simple (Default)</option>
                    <option value="professional">Professional</option>
                    <option value="advanced">Advanced</option>
                  </select>
                </div>
                <div className="setup-style-field">
                  <label htmlFor="setup-answer-style">Answer style</label>
                  <select
                    id="setup-answer-style"
                    className="setup-input"
                    value={answerStyle}
                    onChange={(e) => setAnswerStyle(e.target.value as AnswerStyle)}
                  >
                    <option value="natural">Natural &amp; Human (Default)</option>
                    <option value="concise">Concise</option>
                    <option value="detailed">Detailed</option>
                  </select>
                </div>
                <div className="setup-style-field">
                  <label htmlFor="setup-humanization">Humanization</label>
                  <select
                    id="setup-humanization"
                    className="setup-input"
                    value={humanization}
                    onChange={(e) => setHumanization(e.target.value as Humanization)}
                  >
                    <option value="natural">Natural</option>
                    <option value="conversational">More Conversational</option>
                    <option value="formal">More Formal</option>
                  </select>
                </div>
              </div>
            )}
          </div>

          <Button variant="primary" onClick={startInterview} disabled={starting}>
            {starting ? (
              <span className="btn-spinner">
                <Spinner />
                Starting…
              </span>
            ) : (
              "Start Interview"
            )}
          </Button>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <div className="setup-identity">
        <div className="setup-identity-field">
          <label htmlFor="setup-role">Role</label>
          <input
            id="setup-role"
            className="setup-input"
            value={role}
            onChange={(e) => handleRoleChange(e.target.value)}
            placeholder="e.g. Product Designer"
          />
        </div>
        <div className="setup-identity-field">
          <label htmlFor="setup-company">Company</label>
          <input
            id="setup-company"
            className="setup-input"
            value={company}
            onChange={(e) => handleCompanyChange(e.target.value)}
            placeholder="e.g. Acme Inc."
          />
        </div>
      </div>

      <div className="setup-sections">
        {SECTIONS.map((section) => {
          const state = sections[section.key];
          return (
            <div className="setup-section" key={section.key}>
              <div className="setup-section-head">
                <span className="setup-section-label">{section.label}</span>
                <span className="setup-section-optional">Optional</span>
              </div>

              <div className="setup-section-body">
                {state.fileName ? (
                  <div className="setup-file-chip">
                    <span className="setup-file-name">{state.fileName}</span>
                    <button className="link-button" onClick={() => clearFile(section.key)}>
                      Remove
                    </button>
                  </div>
                ) : (
                  <>
                    <Button variant="secondary" size="sm" onClick={() => pickFile(section.key)}>
                      {section.placeholder}
                    </Button>
                    <textarea
                      className="setup-textarea"
                      value={state.text}
                      onChange={(e) => setText(section.key, e.target.value)}
                      placeholder={section.textareaPlaceholder}
                    />
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {(analyzing || focusSummary) && (
        <div className="setup-focus">
          <div className="setup-focus-head">
            <span className="setup-focus-title">Interview Focus</span>
            {analyzing && <span className="setup-focus-status">Analyzing…</span>}
          </div>
          {focusSummary && (
            <div className="setup-focus-body">
              {(focusSummary.job_title ||
                focusSummary.company ||
                focusSummary.seniority ||
                focusSummary.employment_type) && (
                <p className="setup-focus-line">
                  {[
                    focusSummary.job_title,
                    focusSummary.company,
                    focusSummary.seniority,
                    focusSummary.employment_type,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              )}
              {[
                ["Responsibilities", focusSummary.key_responsibilities],
                ["Focus areas", focusSummary.focus_areas],
                ["Key skills", focusSummary.required_skills],
                ["Technologies", focusSummary.technologies],
                ["Your relevant experience", focusSummary.candidate_highlights],
              ]
                .filter(([, items]) => (items as string[]).length > 0)
                .map(([label, items]) => (
                  <div className="setup-focus-group" key={label as string}>
                    <span className="setup-focus-label">{label as string}</span>
                    <div className="setup-focus-chips">
                      {(items as string[]).map((item) => (
                        <span className="setup-focus-chip" key={item}>
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}

    </div>
  );
}
