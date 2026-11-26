/**
 * Shared API client for Agent Lab v1.0.0.
 *
 * Supports BOTH:
 * 1. AstrBot Native Dashboard Plugin Page bridge (`window.AstrBotPluginView || window.AstrBotPluginPage`)
 *    - Awaits `bridge.ready()` with a 15s timeout
 *    - Strips `/api/` prefix to pass relative endpoints ("v1/state", "v1/workspace", "v1/profiles", "v1/credentials", "v1/health")
 *    - Calls `bridge.requestResize()` after layout updates
 * 2. Standalone Quart / Preview Server via `fetch`
 *    - Reads `<meta name="agent-lab-api-base">` (default `/api`)
 *    - Supports optional `X-Agent-Lab-Token` stored in `sessionStorage` or `?token=` query param
 *
 * Strictly uses GET and POST only.
 */

const memorySession = new Map();
const memoryLocal = new Map();

export const safeSession = {
  getItem(key) {
    if (memorySession.has(key)) return memorySession.get(key);
    try {
      return window.sessionStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, value) {
    const str = String(value ?? "");
    memorySession.set(key, str);
    try {
      window.sessionStorage.setItem(key, str);
    } catch {
      /* opaque-origin iframe fallback */
    }
  },
  removeItem(key) {
    memorySession.delete(key);
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* opaque-origin iframe fallback */
    }
  },
};

export const safeLocal = {
  getItem(key) {
    if (memoryLocal.has(key)) return memoryLocal.get(key);
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, value) {
    const str = String(value ?? "");
    memoryLocal.set(key, str);
    try {
      window.localStorage.setItem(key, str);
    } catch {
      /* opaque-origin iframe fallback */
    }
  },
};

const TOKEN_STORAGE_KEY = "agent_lab_token";
const BRIDGE_READY_TIMEOUT_MS = 15000;

let bridgeReadyPromise = null;
let resizeTimer = null;

function initTokenFromUrl() {
  try {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("token");
    if (token && token.trim()) {
      safeSession.setItem(TOKEN_STORAGE_KEY, token.trim());
    }
  } catch {
    /* ignore */
  }
}
initTokenFromUrl();

export function getAuthToken() {
  return (safeSession.getItem(TOKEN_STORAGE_KEY) || "").trim();
}

export function setAuthToken(token) {
  const clean = String(token || "").trim();
  if (clean) {
    safeSession.setItem(TOKEN_STORAGE_KEY, clean);
  } else {
    safeSession.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function getBridge() {
  return window.AstrBotPluginView || window.AstrBotPluginPage || null;
}

export function isEmbeddedBridge() {
  const b = getBridge();
  return Boolean(b && (typeof b.apiGet === "function" || typeof b.apiPost === "function"));
}

function getApiBase() {
  const meta = document.querySelector('meta[name="agent-lab-api-base"]');
  const raw = (meta?.getAttribute("content") || "/api").trim();
  return raw.replace(/\/+$/, "") || "/api";
}

function stripApiPrefix(endpoint) {
  let clean = String(endpoint || "").trim();
  clean = clean.replace(/^\/+/, "");
  if (clean.startsWith("api/")) {
    clean = clean.slice(4);
  }
  return clean;
}

async function ensureBridgeReady(bridge) {
  if (!bridge || typeof bridge.ready !== "function") {
    return;
  }
  if (!bridgeReadyPromise) {
    bridgeReadyPromise = Promise.race([
      Promise.resolve(bridge.ready()),
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error("AstrBot 插件面板桥接初始化超时（15s），请刷新页面重试。")),
          BRIDGE_READY_TIMEOUT_MS
        )
      ),
    ]).catch((err) => {
      bridgeReadyPromise = null;
      throw err;
    });
  }
  await bridgeReadyPromise;
}

function unwrapPayload(raw) {
  if (raw == null) return {};
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return { ok: true, raw };
    }
  }
  // Handle Axios/AstrBot envelope `{ status: "ok", data: { ... } }` or `{ data: { ok: ... } }`
  let obj = raw;
  if (obj && typeof obj === "object" && "data" in obj && obj.data && typeof obj.data === "object") {
    if (obj.status === "error") {
      const err = new Error(obj.message || obj.error || "接口返回错误");
      err.payload = obj;
      throw err;
    }
    if ("ok" in obj.data || "projects" in obj.data || "profiles" in obj.data || "meta" in obj.data) {
      obj = obj.data;
    }
  }
  if (obj && typeof obj === "object") {
    if (obj.status === "error" || obj.ok === false) {
      const err = new Error(obj.error || obj.message || "操作失败");
      err.payload = obj;
      throw err;
    }
  }
  return obj;
}

export function requestResize() {
  const bridge = getBridge();
  if (!bridge || typeof bridge.requestResize !== "function") return;
  if (resizeTimer) {
    clearTimeout(resizeTimer);
  }
  resizeTimer = setTimeout(() => {
    resizeTimer = null;
    try {
      window.requestAnimationFrame(() => {
        try {
          bridge.requestResize();
        } catch {
          /* ignore */
        }
      });
    } catch {
      try {
        bridge.requestResize();
      } catch {
        /* ignore */
      }
    }
  }, 40);
}

export async function apiGet(endpoint) {
  const rel = stripApiPrefix(endpoint);
  const bridge = getBridge();

  if (bridge && typeof bridge.apiGet === "function") {
    await ensureBridgeReady(bridge);
    const res = await bridge.apiGet(rel);
    return unwrapPayload(res);
  }

  const base = getApiBase();
  const url = `${base}/${rel}`;
  const headers = { Accept: "application/json" };
  const token = getAuthToken();
  if (token) {
    headers["X-Agent-Lab-Token"] = token;
  }

  const resp = await fetch(url, {
    method: "GET",
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });

  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }

  if (resp.status === 401 || resp.status === 403) {
    const err = new Error(data?.error || data?.message || "需要验证访问令牌（X-Agent-Lab-Token）或管理员权限。");
    err.code = "AUTH_REQUIRED";
    err.status = resp.status;
    throw err;
  }
  if (!resp.ok) {
    const err = new Error(data?.error || data?.message || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return unwrapPayload(data);
}

export async function apiPost(endpoint, body = {}) {
  const rel = stripApiPrefix(endpoint);
  const bridge = getBridge();

  if (bridge && typeof bridge.apiPost === "function") {
    await ensureBridgeReady(bridge);
    const res = await bridge.apiPost(rel, body);
    return unwrapPayload(res);
  }

  const base = getApiBase();
  const url = `${base}/${rel}`;
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  const token = getAuthToken();
  if (token) {
    headers["X-Agent-Lab-Token"] = token;
  }

  const resp = await fetch(url, {
    method: "POST",
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: JSON.stringify(body ?? {}),
  });

  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }

  if (resp.status === 401 || resp.status === 403) {
    const err = new Error(data?.error || data?.message || "需要验证访问令牌（X-Agent-Lab-Token）或管理员权限。");
    err.code = "AUTH_REQUIRED";
    err.status = resp.status;
    throw err;
  }
  if (!resp.ok) {
    const err = new Error(data?.error || data?.message || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return unwrapPayload(data);
}
