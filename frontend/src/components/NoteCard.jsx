import React from "react";

const styles = {
  card: {
    background: "#fff",
    borderRadius: 10,
    padding: "16px 20px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" },
  title: { fontSize: 16, fontWeight: 600, color: "#2d3748" },
  meta: { fontSize: 12, color: "#718096" },
  content: { fontSize: 14, color: "#4a5568", lineHeight: 1.6, whiteSpace: "pre-wrap" },
  actions: { display: "flex", gap: 8, marginTop: 4 },
  btnDelete: { background: "#fed7d7", color: "#c53030" },
  btnEdit: { background: "#ebf8ff", color: "#2b6cb0" },
};

export default function NoteCard({ note, onDelete, onEdit }) {
  const date = new Date(note.created_at).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.title}>{note.title}</span>
        <span style={styles.meta}>{note.author} · {date}</span>
      </div>
      <p style={styles.content}>{note.content}</p>
      <div style={styles.actions}>
        <button style={styles.btnEdit} onClick={() => onEdit(note)}>Edit</button>
        <button style={styles.btnDelete} onClick={() => onDelete(note.id)}>Delete</button>
      </div>
    </div>
  );
}
