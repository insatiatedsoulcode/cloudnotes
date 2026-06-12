import React, { useState } from "react";
import { authApi } from "../api/auth";

const s = {
  wrap: {
    minHeight: "100vh", display: "flex", alignItems: "center",
    justifyContent: "center", background: "#edf2f7",
  },
  card: {
    background: "#fff", borderRadius: 12, padding: "36px 40px",
    boxShadow: "0 4px 20px rgba(0,0,0,0.1)", width: 360,
    display: "flex", flexDirection: "column", gap: 16,
  },
  title: { fontSize: 22, fontWeight: 700, color: "#2d3748", marginBottom: 4 },
  label: { fontSize: 12, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4 },
  error: { background: "#fed7d7", color: "#c53030", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  btnPrimary: { background: "#4299e1", color: "#fff", padding: "10px", fontSize: 14, fontWeight: 600 },
  toggle: { textAlign: "center", fontSize: 13, color: "#718096" },
  link: { color: "#4299e1", cursor: "pointer", fontWeight: 600, background: "none", border: "none" },
};

export default function LoginForm({ onLogin }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "register") {
        await authApi.register(email, password);
        // after register, log them in automatically
      }
      const { access_token } = await authApi.login(email, password);
      localStorage.setItem("token", access_token);
      onLogin(email);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={s.wrap}>
      <div style={s.card}>
        <div>
          <div style={s.title}>☁ CloudNotes</div>
          <div style={{ fontSize: 13, color: "#a0aec0" }}>
            {mode === "login" ? "Sign in to your account" : "Create a new account"}
          </div>
        </div>

        {error && <div style={s.error}>⚠ {error}</div>}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={s.label}>Email</label>
            <input
              type="email" value={email} required
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label style={s.label}>Password</label>
            <input
              type="password" value={password} required
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          <button type="submit" style={s.btnPrimary} disabled={loading}>
            {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        <div style={s.toggle}>
          {mode === "login" ? "Don't have an account? " : "Already have an account? "}
          <button style={s.link} onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
            {mode === "login" ? "Register" : "Sign In"}
          </button>
        </div>
      </div>
    </div>
  );
}
