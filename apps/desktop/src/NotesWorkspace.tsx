import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import redlyLogo from "./assets/redly-logo.png";
import { NotesList, type Note } from "./NotesList";
import { NoteEditor } from "./NoteEditor";
import { EmptyState } from "./ui";

interface Props {
  onExit: () => void;
}

export function NotesWorkspace({ onExit }: Props) {
  const [selected, setSelected] = useState<Note | null>(null);
  const [listRefreshKey, setListRefreshKey] = useState(0);

  const handleCreate = useCallback(async () => {
    try {
      const note = await invoke<Note>("create_note", { title: "Untitled note", body: "" });
      setSelected(note);
      setListRefreshKey((k) => k + 1);
    } catch (e) {
      console.error("Failed to create note:", e);
    }
  }, []);

  const handleNoteUpdated = useCallback((note: Note) => {
    setSelected(note);
    setListRefreshKey((k) => k + 1);
  }, []);

  const handleNoteDeleted = useCallback(() => {
    setSelected(null);
    setListRefreshKey((k) => k + 1);
  }, []);

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <button className="workspace-back-btn" onClick={onExit} title="Back to REDLY home">
          ← Back
        </button>
        <button className="workspace-brand" onClick={onExit} title="Back to REDLY home">
          <img className="workspace-logo" src={redlyLogo} alt="REDLY" />
          <span className="workspace-wordmark">REDLY</span>
        </button>
      </header>

      <div className="workspace-body">
        <div className="notes-list-pane">
          <NotesList
            refreshKey={listRefreshKey}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            onCreate={handleCreate}
          />
        </div>

        <div className="workspace-main">
          {selected ? (
            <NoteEditor
              key={selected.id}
              note={selected}
              onUpdated={handleNoteUpdated}
              onDeleted={handleNoteDeleted}
            />
          ) : (
            <EmptyState
              icon="📝"
              title="Select or create a note"
              description="Choose a note from the list, or start a new one."
            />
          )}
        </div>
      </div>
    </div>
  );
}
