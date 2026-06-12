const BASE = "/api";

export const authApi = {
  register: async (email, password) => {
    console.log("%c[Auth] REGISTER", "color: #805ad5; font-weight: bold", { email });
    const res = await fetch(`${BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    console.log("%c[Auth] REGISTER → success", "color: #276749", data);
    return data;
  },

  login: async (email, password) => {
    console.log("%c[Auth] LOGIN", "color: #805ad5; font-weight: bold", { email });
    // OAuth2 password flow requires form-encoded body, not JSON.
    // FastAPI's OAuth2PasswordRequestForm reads 'username' + 'password' fields.
    const body = new URLSearchParams({ username: email, password });
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    console.log("%c[Auth] LOGIN → token received", "color: #276749");
    return data; // { access_token, token_type }
  },
};
