import React, { useState, useEffect } from "react";

const TITLE_MAX = 255;
const CONTENT_MAX = 50_000;

const styles = {
  form: {
    background: "#fff", borderRadius: 10, padding: "20px 24px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)", display: "flex", flexDirection: "column", gap: 12,
  },
  label: { fontSize: 12, fontWeight: 600, color: "#718096", marginBottom: 4, display: "block" },
  labelRow: { display: "flex", justifyContent: "space-between", alignItems: "baseline" },
  counter: (over) => ({
    fontSize: 11, fontWeight: 500,
    color: over ? "#c53030" : "#a0aec0",
  }),
  row: { display: "flex", gap: 12 },
  btnPrimary: { background: "#4299e1", color: "#fff" },
  btnSecondary: { background: "#edf2f7", color: "#4a5568" },
  error: {
    background: "#fff5f5", border: "1px solid #feb2b2", color: "#c53030",
    borderRadius: 6, padding: "10px 14px", fontSize: 13, lineHeight: 1.5,
  },
};

export default function NoteForm({ onSubmit, editNote, onCancel }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (editNote) {
      setTitle(editNote.title);
      setContent(editNote.content);
    } else {
      setTitle(""); setContent("");
    }
    setError(null);
  }, [editNote]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    setError(null);
    setLoading(true);
    try {
      await onSubmit({ title: title.trim(), content: content.trim() });
      setTitle(""); setContent("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const titleOver = title.length > TITLE_MAX;
  const contentOver = content.length > CONTENT_MAX;

  return (
    <form style={styles.form} onSubmit={handleSubmit}>
      <h3 style={{ fontSize: 15, fontWeight: 600 }}>{editNote ? "Edit Note" : "New Note"}</h3>

      {error && <div style={styles.error}>{error}</div>}

      <div>
        <div style={styles.labelRow}>
          <label style={styles.label}>Title</label>
          <span style={styles.counter(titleOver)}>
            {title.length} / {TITLE_MAX}
          </span>
        </div>
        <input
          value={title}
          onChange={e => { setTitle(e.target.value); setError(null); }}
          placeholder="Note title..."
          required
          style={titleOver ? { borderColor: "#fc8181", outline: "none" } : {}}
        />
      </div>

      <div>
        <div style={styles.labelRow}>
          <label style={styles.label}>Content</label>
          <span style={styles.counter(contentOver)}>
            {content.length.toLocaleString()} / {CONTENT_MAX.toLocaleString()}
          </span>
        </div>
        <textarea
          value={content}
          onChange={e => { setContent(e.target.value); setError(null); }}
          placeholder="Write your note..."
          rows={4}
          style={{ resize: "vertical", ...(contentOver ? { borderColor: "#fc8181", outline: "none" } : {}) }}
          required
        />
      </div>

      <div style={styles.row}>
        <button type="submit" style={styles.btnPrimary} disabled={loading || titleOver || contentOver}>
          {loading ? "Saving..." : editNote ? "Update" : "Add Note"}
        </button>
        {editNote && (
          <button type="button" style={styles.btnSecondary} onClick={onCancel}>Cancel</button>
        )}
      </div>
    </form>
  );
}
