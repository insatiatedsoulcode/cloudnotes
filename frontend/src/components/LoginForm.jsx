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
  sub: { fontSize: 13, color: "#a0aec0" },
  label: { fontSize: 12, fontWeight: 600, color: "#718096", display: "block", marginBottom: 4 },
  error: { background: "#fed7d7", color: "#c53030", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  success: { background: "#c6f6d5", color: "#276749", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  btnPrimary: { background: "#4299e1", color: "#fff", padding: "10px", fontSize: 14, fontWeight: 600 },
  toggle: { textAlign: "center", fontSize: 13, color: "#718096" },
  link: { color: "#4299e1", cursor: "pointer", fontWeight: 600, background: "none", border: "none", padding: 0 },
  forgotRow: { textAlign: "right", marginTop: -4 },
};

// mode: "login" | "register" | "reset"
export default function LoginForm({ onLogin }) {
  const [mode, setMode]           = useState("login");
  const [email, setEmail]         = useState("");
  const [password, setPassword]   = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError]         = useState(null);
  const [success, setSuccess]     = useState(null);
  const [loading, setLoading]     = useState(false);

  function switchMode(next) {
    setMode(next);
    setError(null);
    setSuccess(null);
    setPassword("");
    setNewPassword("");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);

    try {
      if (mode === "register") {
        await authApi.register(email, password);
        const { access_token } = await authApi.login(email, password);
        localStorage.setItem("token", access_token);
        onLogin(email);

      } else if (mode === "login") {
        const { access_token } = await authApi.login(email, password);
        localStorage.setItem("token", access_token);
        onLogin(email);

      } else if (mode === "reset") {
        await authApi.devResetPassword(email, newPassword);
        setSuccess("Password reset! You can now sign in with your new password.");
        switchMode("login");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const titles = {
    login:    "Sign in to your account",
    register: "Create a new account",
    reset:    "Reset your password",
  };

  const btnLabel = loading
    ? "Please wait..."
    : mode === "login"    ? "Sign In"
    : mode === "register" ? "Create Account"
    : "Reset Password";

  return (
    <div style={s.wrap}>
      <div style={s.card}>
        <div>
          <div style={s.title}>☁ CloudNotes</div>
          <div style={s.sub}>{titles[mode]}</div>
        </div>

        {error   && <div style={s.error}>⚠ {error}</div>}
        {success && <div style={s.success}>✓ {success}</div>}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={s.label}>Email</label>
            <input
              type="email" value={email} required
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>

          {mode !== "reset" && (
            <div>
              <label style={s.label}>Password</label>
              <input
                type="password" value={password} required
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
              />
              {mode === "login" && (
                <div style={s.forgotRow}>
                  <button type="button" style={{ ...s.link, fontSize: 12 }}
                    onClick={() => switchMode("reset")}>
                    Forgot password?
                  </button>
                </div>
              )}
            </div>
          )}

          {mode === "reset" && (
            <div>
              <label style={s.label}>New Password</label>
              <input
                type="password" value={newPassword} required minLength={8}
                onChange={e => setNewPassword(e.target.value)}
                placeholder="Min 8 characters"
              />
            </div>
          )}

          <button type="submit" style={s.btnPrimary} disabled={loading}>
            {btnLabel}
          </button>
        </form>

        <div style={s.toggle}>
          {mode === "login" && (
            <>Don't have an account? <button style={s.link} onClick={() => switchMode("register")}>Register</button></>
          )}
          {mode === "register" && (
            <>Already have an account? <button style={s.link} onClick={() => switchMode("login")}>Sign In</button></>
          )}
          {mode === "reset" && (
            <>Remembered it? <button style={s.link} onClick={() => switchMode("login")}>Sign In</button></>
          )}
        </div>
      </div>
    </div>
  );
}
