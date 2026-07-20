// AstrBot plugin page bridge smoke test: extracts the production API adapter.
const fs = require("fs");
const src = fs.readFileSync("pages/agent-lab/app.js", "utf8");

function extract(name) {
  const marker = "function " + name + "(";
  let i = src.indexOf(marker);
  if (i < 0) throw new Error("not found: " + name);
  if (src.slice(Math.max(0, i - 6), i) === "async ") i -= 6;
  let paren = src.indexOf("(", i), parenDepth = 0, quote = null, escaped = false, j = -1;
  for (let k = paren; k < src.length; k++) {
    const c = src[k];
    if (quote) {
      if (escaped) escaped = false;
      else if (c === "\\") escaped = true;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "(") parenDepth++;
    else if (c === ")") { parenDepth--; if (parenDepth === 0) { j = src.indexOf("{", k); break; } }
  }
  if (j < 0) throw new Error("body not found: " + name);
  let depth = 0; quote = null; escaped = false;
  for (let k = j; k < src.length; k++) {
    const c = src[k];
    if (quote) {
      if (escaped) escaped = false;
      else if (c === "\\") escaped = true;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return src.slice(i, k + 1); }
  }
  throw new Error("unbalanced: " + name);
}

const calls = [];
global.window = {
  AstrBotPluginPage: {
    ready: async () => calls.push(["ready"]),
    apiGet: async (endpoint, params) => { calls.push(["get", endpoint, params]); return { ok: true, endpoint, params }; },
    apiPost: async (endpoint, body) => { calls.push(["post", endpoint, body]); return { ok: true, endpoint, body }; },
  },
};
global.location = { origin: "http://astrbot.local" };
global.document = { querySelector: () => ({ content: "/api" }) };
function token() { return ""; }

const code = ["apiUrl", "pluginPageRequest", "pluginPageBridge", "api"].map(extract).join("\n\n");
const api = new Function("window", "location", "document", "token", `${code}; return api;`)(window, location, document, token);

(async () => {
  const state = await api("/api/state");
  if (state.endpoint !== "state") throw new Error("state endpoint mismatch");
  const logs = await api("/api/task/logs?task_id=task-1");
  if (logs.endpoint !== "task/logs" || logs.params.task_id !== "task-1") throw new Error("GET params mismatch");
  const finish = await api("/api/task/finish", { method: "POST", body: { umo: "u", summary: "done" } });
  if (finish.endpoint !== "task/finish" || finish.body.summary !== "done") throw new Error("POST body mismatch");
  if (!calls.some((row) => row[0] === "get") || !calls.some((row) => row[0] === "post")) throw new Error("bridge not used");
  console.log("ASTRBOT PLUGIN PAGE BRIDGE SMOKE PASSED");
})().catch((error) => { console.error(error); process.exit(1); });
