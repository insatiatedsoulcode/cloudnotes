const BASE = "/api";

// Reads token from localStorage on every request — no need to pass it around.
function getAuthHeader() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const method = options.method || "GET";
  const url = `${BASE}${path}`;

  console.group(`%c[API] ${method} ${url}`, "color: #2b6cb0; font-weight: bold");
  if (options.body) {
    console.log("%cRequest body:", "color: #718096", JSON.parse(options.body));
  }

  const t0 = performance.now();
  try {
    const res = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeader(),
        ...options.headers,
      },
      ...options,
    });

    const duration = (performance.now() - t0).toFixed(1);
    console.log(
      `%cStatus: ${res.status} ${res.statusText}  (${duration}ms)`,
      res.ok ? "color: #276749" : "color: #c53030"
    );

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.error("%cError body:", "color: #c53030", err);
      console.groupEnd();
      // Pydantic validation errors: detail is an array of {msg, loc, ...}
      // FastAPI business errors: detail is a plain string
      const detail = err.detail;
      let message;
      if (Array.isArray(detail)) {
        message = detail.map(e => e.msg.replace(/^Value error,\s*/i, "")).join("; ");
      } else {
        message = detail || `HTTP ${res.status}`;
      }
      throw new Error(message);
    }

    if (res.status === 204) {
      console.log("%cResponse: (no content)", "color: #718096");
      console.groupEnd();
      return null;
    }

    const data = await res.json();
    console.log("%cResponse data:", "color: #276749", data);
    console.groupEnd();
    return data;

  } catch (err) {
    const duration = (performance.now() - t0).toFixed(1);
    console.error(`%cFetch failed after ${duration}ms:`, "color: #c53030", err.message);
    console.groupEnd();
    throw err;
  }
}

export const notesApi = {
  list:   ()         => request("/notes/"),
  get:    (id)       => request(`/notes/${id}`),
  create: (data)     => request("/notes/",      { method: "POST",   body: JSON.stringify(data) }),
  update: (id, data) => request(`/notes/${id}`,  { method: "PUT",    body: JSON.stringify(data) }),
  delete: (id)       => request(`/notes/${id}`,  { method: "DELETE" }),
};
