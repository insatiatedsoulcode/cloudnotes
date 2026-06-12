import React, { useState, useEffect } from "react";

const styles = {
  form: {
    background: "#fff", borderRadius: 10, padding: "20px 24px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)", display: "flex", flexDirection: "column", gap: 12,
  },
  label: { fontSize: 12, fontWeight: 600, color: "#718096", marginBottom: 4, display: "block" },
  row: { display: "flex", gap: 12 },
  btnPrimary: { background: "#4299e1", color: "#fff" },
  btnSecondary: { background: "#edf2f7", color: "#4a5568" },
};

export default function NoteForm({ onSubmit, editNote, onCancel }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (editNote) {
      setTitle(editNote.title);
      setContent(editNote.content);
    } else {
      setTitle(""); setContent("");
    }
  }, [editNote]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    setLoading(true);
    try {
      await onSubmit({ title: title.trim(), content: content.trim() });
      setTitle(""); setContent("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form style={styles.form} onSubmit={handleSubmit}>
      <h3 style={{ fontSize: 15, fontWeight: 600 }}>{editNote ? "Edit Note" : "New Note"}</h3>
      <div>
        <label style={styles.label}>Title</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Note title..." required />
      </div>
      <div>
        <label style={styles.label}>Content</label>
        <textarea
          value={content} onChange={e => setContent(e.target.value)}
          placeholder="Write your note..." rows={4} style={{ resize: "vertical" }} required
        />
      </div>
      <div style={styles.row}>
        <button type="submit" style={styles.btnPrimary} disabled={loading}>
          {loading ? "Saving..." : editNote ? "Update" : "Add Note"}
        </button>
        {editNote && (
          <button type="button" style={styles.btnSecondary} onClick={onCancel}>Cancel</button>
        )}
      </div>
    </form>
  );
}
