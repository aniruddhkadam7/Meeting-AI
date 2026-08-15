import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Button } from "./ui";
import { NoteAIPanel } from "./NoteAIPanel";
import type { Note } from "./NotesList";

interface Props {
  note: Note;
  onUpdated: (note: Note) => void;
  onDeleted: () => void;
}

const AUTOSAVE_DEBOUNCE_MS = 800;

export function NoteEditor({ note, onUpdated, onDeleted }: Props) {
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body);
  const [project, setProject] = useState(note.project ?? "");
  const [tagsText, setTagsText] = useState(note.tags.join(", "));
  const [recording, setRecording] = useState(false);
  const [dictationHint, setDictationHint] = useState("");
  const [linkPickerOpen, setLinkPickerOpen] = useState(false);
  const [allNotes, setAllNotes] = useState<Note[]>([]);
  const [linkedIds, setLinkedIds] = useState<string[]>(note.linked_note_ids);
  const [error, setError] = useState<string | null>(null);

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noteId = note.id;

  const persist = useCallback(
    async (fields: Partial<{ title: string; body: string; project: string; tags: string[]; linkedNoteIds: string[] }>) => {
      try {
        const updated = await invoke<Note>("update_note", { id: noteId, ...fields });
        onUpdated(updated);
      } catch (e) {
        setError(String(e));
      }
    },
    [noteId, onUpdated],
  );

  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const tags = tagsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      persist({ title, body, project, tags });
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, body, project, tagsText]);

  useEffect(() => {
    if (!recording) return;
    const unlistenPartial = listen<string>("notes:dictation-partial", (e) => {
      setDictationHint(e.payload);
    });
    return () => {
      unlistenPartial.then((fn) => fn());
    };
  }, [recording]);

  const toggleDictation = useCallback(async () => {
    setError(null);
    if (!recording) {
      try {
        await invoke("start_note_dictation");
        setRecording(true);
        setDictationHint("");
      } catch (e) {
        setError(String(e));
      }
      return;
    }
    try {
      const text = await invoke<string>("stop_note_dictation");
      setRecording(false);
      setDictationHint("");
      if (text.trim()) {
        setBody((prev) => (prev.trim() ? `${prev.trim()} ${text.trim()}` : text.trim()));
      }
    } catch (e) {
      setError(String(e));
      setRecording(false);
    }
  }, [recording]);

  const deleteNote = useCallback(async () => {
    try {
      await invoke("delete_note", { id: noteId });
      onDeleted();
    } catch (e) {
      setError(String(e));
    }
  }, [noteId, onDeleted]);

  const openLinkPicker = useCallback(async () => {
    try {
      const notes = await invoke<Note[]>("list_notes");
      setAllNotes(notes.filter((n) => n.id !== noteId));
      setLinkPickerOpen(true);
    } catch (e) {
      setError(String(e));
    }
  }, [noteId]);

  const toggleLink = useCallback(
    (id: string) => {
      const next = linkedIds.includes(id) ? linkedIds.filter((x) => x !== id) : [...linkedIds, id];
      setLinkedIds(next);
      persist({ linkedNoteIds: next });
    },
    [linkedIds, persist],
  );

  const linkedNotes = allNotes.filter((n) => linkedIds.includes(n.id));

  return (
    <div className="note-editor">
      {error && <p className="error">{error}</p>}

      <div className="note-editor-head">
        <input
          className="setup-input note-editor-title"
          placeholder="Untitled note"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Button variant="danger" size="sm" onClick={deleteNote}>
          Delete
        </Button>
      </div>

      <div className="note-editor-meta">
        <input
          className="setup-input"
          placeholder="Project"
          value={project}
          onChange={(e) => setProject(e.target.value)}
        />
        <input
          className="setup-input"
          placeholder="Tags, comma separated"
          value={tagsText}
          onChange={(e) => setTagsText(e.target.value)}
        />
      </div>

      <div className="note-editor-toolbar">
        <button
          className={["notes-mic-btn", recording ? "recording" : ""].filter(Boolean).join(" ")}
          onClick={toggleDictation}
          title={recording ? "Stop dictation" : "Start voice dictation"}
        >
          {recording ? "● Stop" : "🎤 Dictate"}
        </button>
        {recording && dictationHint && <span className="notes-dictation-hint">hearing: {dictationHint}</span>}

        <button className="link-button" onClick={openLinkPicker}>
          Link related note
        </button>
      </div>

      {linkedNotes.length > 0 && (
        <div className="notes-linked-chips">
          {linkedNotes.map((n) => (
            <span key={n.id} className="setup-focus-chip">
              {n.title || "Untitled"}
            </span>
          ))}
        </div>
      )}

      {linkPickerOpen && (
        <div className="notes-link-picker">
          <div className="notes-link-picker-head">
            <span className="setup-focus-label">Select notes to link</span>
            <button className="link-button" onClick={() => setLinkPickerOpen(false)}>
              Done
            </button>
          </div>
          <div className="notes-link-picker-list">
            {allNotes.length === 0 ? (
              <p className="hint small">No other notes yet.</p>
            ) : (
              allNotes.map((n) => (
                <label key={n.id} className="notes-link-picker-item">
                  <input type="checkbox" checked={linkedIds.includes(n.id)} onChange={() => toggleLink(n.id)} />
                  {n.title || "Untitled note"}
                </label>
              ))
            )}
          </div>
        </div>
      )}

      <textarea
        className="setup-textarea note-editor-body"
        placeholder="Start typing…"
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />

      <NoteAIPanel note={{ ...note, title, body }} />
    </div>
  );
}
