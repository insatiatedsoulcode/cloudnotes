import React, { useState, useEffect, useCallback } from "react";
import { notesApi } from "./api/notes";
import NoteCard from "./components/NoteCard";
import NoteForm from "./components/NoteForm";
import LoginForm from "./components/LoginForm";

const styles = {
  header: {
    background: "#2b6cb0", color: "#fff", padding: "16px 32px",
    display: "flex", alignItems: "center", gap: 12,
    boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
  },
  logo: { fontSize: 22, fontWeight: 700 },
  headerRight: { marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 },
  env: { background: "rgba(255,255,255,0.2)", padding: "4px 10px", borderRadius: 20, fontSize: 12 },
  userBadge: { fontSize: 13, opacity: 0.9 },
  btnLogout: {
    background: "rgba(255,255,255,0.15)", color: "#fff", border: "1px solid rgba(255,255,255,0.3)",
    padding: "4px 12px", borderRadius: 6, fontSize: 12, cursor: "pointer",
  },
  main: { maxWidth: 800, margin: "32px auto", padding: "0 16px", display: "flex", flexDirection: "column", gap: 24 },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 },
  error: { background: "#fed7d7", color: "#c53030", padding: "12px 16px", borderRadius: 8, fontSize: 14 },
  empty: { textAlign: "center", color: "#a0aec0", padding: "48px 0", fontSize: 15 },
};

const tag = (label) => `%c[App] ${label}`;
const blue  = "color: #2b6cb0; font-weight: bold";
const green = "color: #276749";
const red   = "color: #c53030";

export default function App() {
  const [userEmail, setUserEmail] = useState(() => localStorage.getItem("userEmail"));
  const [notes, setNotes] = useState([]);
  const [editNote, setEditNote] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchNotes = useCallback(async () => {
    console.log(tag("fetchNotes"), blue);
    try {
      const data = await notesApi.list();
      setNotes(data);
      setError(null);
      console.log(tag(`fetchNotes → ${data.length} note(s) loaded`), green);
    } catch (e) {
      // 401 = token expired → force logout
      if (e.message.includes("401") || e.message.toLowerCase().includes("invalid")) {
        console.warn(tag("fetchNotes → 401, logging out"), red);
        handleLogout();
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (userEmail) {
      console.log(tag("mount — user found in localStorage, loading notes"), blue);
      fetchNotes();
    } else {
      setLoading(false);
    }
  }, [userEmail, fetchNotes]);

  function handleLogin(email) {
    localStorage.setItem("userEmail", email);
    setUserEmail(email);
    console.log(tag(`login → email=${email}`), green);
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("userEmail");
    setUserEmail(null);
    setNotes([]);
    console.log(tag("logout"), blue);
  }

  async function handleCreate(data) {
    console.log(tag("handleCreate"), blue, data);
    await notesApi.create(data);
    fetchNotes();
  }

  async function handleUpdate(data) {
    console.log(tag(`handleUpdate  id=${editNote.id}`), blue, data);
    await notesApi.update(editNote.id, data);
    setEditNote(null);
    fetchNotes();
  }

  async function handleDelete(id) {
    if (!window.confirm("Delete this note?")) return;
    console.log(tag(`handleDelete  id=${id}`), blue);
    await notesApi.delete(id);
    fetchNotes();
  }

  if (!userEmail) return <LoginForm onLogin={handleLogin} />;

  const env = import.meta.env.VITE_APP_ENV || "local";

  return (
    <>
      <header style={styles.header}>
        <span style={styles.logo}>☁ CloudNotes</span>
        <div style={styles.headerRight}>
          <span style={styles.userBadge}>{userEmail}</span>
          <span style={styles.env}>env: {env}</span>
          <button style={styles.btnLogout} onClick={handleLogout}>Logout</button>
        </div>
      </header>

      <main style={styles.main}>
        {error && <div style={styles.error}>⚠ {error}</div>}

        <NoteForm
          onSubmit={editNote ? handleUpdate : handleCreate}
          editNote={editNote}
          onCancel={() => setEditNote(null)}
        />

        {loading ? (
          <p style={styles.empty}>Loading notes...</p>
        ) : notes.length === 0 ? (
          <p style={styles.empty}>No notes yet. Create one above!</p>
        ) : (
          <div style={styles.grid}>
            {notes.map(n => (
              <NoteCard key={n.id} note={n} onDelete={handleDelete} onEdit={setEditNote} />
            ))}
          </div>
        )}
      </main>
    </>
  );
}
