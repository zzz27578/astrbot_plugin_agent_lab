const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let state = null;

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
    ...(state.plugins || []).map((item) =>
      pill(`${item.activated ? "开" : "关"} · ${item.display_name || item.name}`, item.activated),
    ),
  );
  $("tools").replaceChildren(
    ...(state.tools || []).map((item) => pill(`${item.active ? "开" : "关"} · ${item.name}`, item.active)),
  );
  $("skills").replaceChildren(
    ...(state.skills || []).map((item) => pill(`${item.active ? "开" : "关"} · ${item.name}`, item.active)),
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

