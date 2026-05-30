const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let state = null;
let currentAgent = null;

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function row(text, sub = "") {
  const el = document.createElement("div");
  el.className = "row";
  el.innerHTML = `<strong>${escapeHtml(text)}</strong>${sub ? `<span>${escapeHtml(sub)}</span>` : ""}`;
  return el;
}

function pill(text, active) {
  const el = document.createElement("div");
  el.className = `pill ${active ? "active" : ""}`;
  el.textContent = text;
  return el;
}

function escapeHtml(input) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function render() {
  currentAgent = clone((state.agents || [])[0] || {});
  $("agent-name").value = currentAgent.name || "";
  $("trigger-mode").value = currentAgent.trigger_mode || "confirm";
  $("system-prompt").value = currentAgent.system_prompt || "";
  $("task-prompt").value = currentAgent.task_prompt || "";

  $("agents").replaceChildren(
    ...(state.agents || []).map((agent) =>
      row(agent.name, `${agent.agent_id} · ${agent.trigger_mode}`),
    ),
  );
  $("tasks").replaceChildren(
    ...((state.tasks || []).length
      ? state.tasks.map((task) =>
          row(task.root_goal || task.task_id, `${task.status} · ${task.task_id}`),
        )
      : [row("暂无任务", "可以在私聊里 /agentlab start，或用上方测试入口")]),
  );
  $("plugins").replaceChildren(
    ...(state.plugins || []).map((item) => {
      const override = currentAgent.plugin_overrides?.[item.name];
      const active = override === undefined ? item.activated : Boolean(override);
      const el = pill(`${active ? "开" : "关"} · ${item.display_name || item.name}`, active);
      el.addEventListener("click", () => {
        currentAgent.plugin_overrides ||= {};
        currentAgent.plugin_overrides[item.name] = !active;
        renderFromCurrentAgent();
      });
      return el;
    }),
  );
  $("tools").replaceChildren(
    ...(state.tools || []).map((item) => {
      const whiteList = new Set(currentAgent.enabled_tools || []);
      const active = whiteList.size === 0 ? item.active : whiteList.has(item.name);
      const el = pill(`${active ? "开" : "关"} · ${item.name}`, active);
      el.addEventListener("click", () => {
        const next = new Set(currentAgent.enabled_tools || []);
        if (next.has(item.name)) next.delete(item.name);
        else next.add(item.name);
        currentAgent.enabled_tools = Array.from(next);
        renderFromCurrentAgent();
      });
      return el;
    }),
  );
  $("skills").replaceChildren(
    ...(state.skills || []).map((item) => {
      const selected = new Set(currentAgent.enabled_skills || []);
      const active = selected.size === 0 ? item.active : selected.has(item.name);
      const el = pill(`${active ? "开" : "关"} · ${item.name}`, active);
      el.addEventListener("click", () => {
        const next = new Set(currentAgent.enabled_skills || []);
        if (next.has(item.name)) next.delete(item.name);
        else next.add(item.name);
        currentAgent.enabled_skills = Array.from(next);
        renderFromCurrentAgent();
      });
      return el;
    }),
  );
  $("modules").replaceChildren(
    ...(state.modules || []).map((mod) => {
      const el = document.createElement("div");
      el.className = "module";
      el.innerHTML = `<strong>${escapeHtml(mod.name)}</strong><p>${escapeHtml(mod.description)}</p><small>${escapeHtml(mod.source)}</small>`;
      return el;
    }),
  );
}

function renderFromCurrentAgent() {
  const preserved = currentAgent;
  const previousState = state;
  state = { ...state, agents: [preserved, ...(state.agents || []).slice(1)] };
  render();
  state = previousState;
  currentAgent = preserved;
  $("agent-name").value = currentAgent.name || "";
  $("trigger-mode").value = currentAgent.trigger_mode || "confirm";
  $("system-prompt").value = currentAgent.system_prompt || "";
  $("task-prompt").value = currentAgent.task_prompt || "";
}

async function load() {
  state = await bridge.apiGet("state");
  render();
}

async function post(endpoint, body) {
  $("result").textContent = "请求中...";
  try {
    const result = await bridge.apiPost(endpoint, body);
    $("result").textContent = JSON.stringify(result, null, 2);
    await load();
  } catch (error) {
    $("result").textContent = String(error?.stack || error);
  }
}

function umo() {
  return $("umo").value.trim();
}

await bridge.ready();
await load();

$("refresh").addEventListener("click", load);
$("save-agent").addEventListener("click", async () => {
  currentAgent.name = $("agent-name").value.trim() || "Agent";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.system_prompt = $("system-prompt").value;
  currentAgent.task_prompt = $("task-prompt").value;
  await post("agents", currentAgent);
});
$("start").addEventListener("click", () =>
  post("task/start", {
    umo: umo(),
    goal: $("goal").value,
    completion_conditions: "用户验收通过",
  }),
);
$("tick").addEventListener("click", () => post("task/tick", { umo: umo() }));
$("heartbeat-on").addEventListener("click", () =>
  post("task/heartbeat", { umo: umo(), enabled: true }),
);
$("heartbeat-off").addEventListener("click", () =>
  post("task/heartbeat", { umo: umo(), enabled: false }),
);
$("finish").addEventListener("click", () =>
  post("task/finish", {
    umo: umo(),
    status: "completed",
    summary: "WebUI 手动完成。",
  }),
);
