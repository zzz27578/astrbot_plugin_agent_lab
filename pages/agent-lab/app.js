const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let state = null;
let currentAgent = null;
let selectedTaskId = "";

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
  const tasks = state.tasks || [];
  if (tasks.length && !tasks.some((task) => task.task_id === selectedTaskId)) {
    selectedTaskId = tasks[0].task_id;
  }
  if (!tasks.length) {
    selectedTaskId = "";
  }
  currentAgent.memory_policy ||= {};
  currentAgent.approval_policy ||= {};
  currentAgent.heartbeat_policy ||= {};
  $("agent-enabled").checked = currentAgent.enabled !== false;
  $("agent-name").value = currentAgent.name || "";
  $("trigger-mode").value = currentAgent.trigger_mode || "confirm";
  $("memory-mode").value = currentAgent.memory_policy.mode || "task_filtered";
  $("approval-mode").value = currentAgent.approval_policy.mode || "work";
  $("heartbeat-mode").value = currentAgent.heartbeat_policy.mode || "manual";
  $("heartbeat-allowed").checked = currentAgent.heartbeat_policy.allowed !== false;
  $("system-prompt").value = currentAgent.system_prompt || "";
  $("task-prompt").value = currentAgent.task_prompt || "";

  $("agents").replaceChildren(
    ...(state.agents || []).map((agent) =>
      row(agent.name, `${agent.agent_id} · ${agent.trigger_mode}`),
    ),
  );
  $("tasks").replaceChildren(
    ...(tasks.length
      ? tasks.map((task) => {
          const el = row(task.root_goal || task.task_id, `${task.status} · ${task.task_id}`);
          if (selectedTaskId === task.task_id) el.classList.add("selected");
          el.addEventListener("click", () => {
            selectedTaskId = task.task_id;
            render();
          });
          return el;
        })
      : [row("暂无任务", "可以在私聊里 /agentlab start，或用上方测试入口")]),
  );
  $("archives").replaceChildren(
    ...((state.archives || []).length
      ? state.archives.slice(0, 8).map((task) =>
          row(task.root_goal || task.task_id, `${task.status} · ${task.finished_at || task.task_id}`),
        )
      : [row("暂无归档", "完成或取消任务后会出现在这里")]),
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
      const meta = item.risk ? ` · ${item.risk}` : "";
      const source = item.source === "builtin_catalog" ? " · builtin" : "";
      const el = pill(`${active ? "开" : "关"} · ${item.name}${meta}${source}`, active);
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
      const selected = new Set(currentAgent.module_ids || []);
      const active = selected.has(mod.module_id);
      const el = document.createElement("div");
      el.className = `module ${active ? "active" : ""}`;
      el.innerHTML = `<strong>${escapeHtml(mod.name)}</strong><p>${escapeHtml(mod.description)}</p><small>${escapeHtml(mod.source)}</small>`;
      el.addEventListener("click", () => {
        const next = new Set(currentAgent.module_ids || []);
        if (next.has(mod.module_id)) next.delete(mod.module_id);
        else next.add(mod.module_id);
        currentAgent.module_ids = Array.from(next);
        renderFromCurrentAgent();
      });
      return el;
    }),
  );
  renderTaskReview();
}

function renderFromCurrentAgent() {
  const preserved = currentAgent;
  const previousState = state;
  state = { ...state, agents: [preserved, ...(state.agents || []).slice(1)] };
  render();
  state = previousState;
  currentAgent = preserved;
  $("agent-enabled").checked = currentAgent.enabled !== false;
  $("agent-name").value = currentAgent.name || "";
  $("trigger-mode").value = currentAgent.trigger_mode || "confirm";
  $("memory-mode").value = currentAgent.memory_policy?.mode || "task_filtered";
  $("approval-mode").value = currentAgent.approval_policy?.mode || "work";
  $("heartbeat-mode").value = currentAgent.heartbeat_policy?.mode || "manual";
  $("heartbeat-allowed").checked = currentAgent.heartbeat_policy?.allowed !== false;
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

function activeTask() {
  const tasks = state.tasks || [];
  return tasks.find((task) => task.task_id === selectedTaskId) || tasks[0] || null;
}

function renderTaskReview() {
  const task = activeTask();
  if (!task) {
    $("task-review").textContent = "暂无 active task。";
    $("approvals").replaceChildren();
    return;
  }
  selectedTaskId = task.task_id;
  $("task-review").innerHTML = `
    <dl>
      <dt>Task</dt><dd>${escapeHtml(task.task_id)}</dd>
      <dt>Status</dt><dd>${escapeHtml(task.status)}</dd>
      <dt>Goal</dt><dd>${escapeHtml(task.root_goal || "-")}</dd>
      <dt>Next</dt><dd>${escapeHtml(task.next_step || "-")}</dd>
      <dt>Progress</dt><dd>${escapeHtml(task.last_confirmed_progress || "-")}</dd>
      <dt>Heartbeat</dt><dd>${task.heartbeat?.enabled ? "on" : "off"}</dd>
    </dl>
    <div class="actions">
      <button id="review-tick">Tick</button>
      <button id="review-heartbeat">${task.heartbeat?.enabled ? "关心跳" : "开心跳"}</button>
      <button id="review-finish">完成</button>
      <button id="review-cancel" class="danger">取消</button>
    </div>
  `;
  $("review-tick").addEventListener("click", () => post("task/tick", { umo: task.umo }));
  $("review-heartbeat").addEventListener("click", () =>
    post("task/heartbeat", { umo: task.umo, enabled: !task.heartbeat?.enabled }),
  );
  $("review-finish").addEventListener("click", () =>
    post("task/finish", { umo: task.umo, status: "completed", summary: "WebUI 审查完成。" }),
  );
  $("review-cancel").addEventListener("click", () =>
    post("task/cancel", { umo: task.umo, reason: "WebUI 审查取消。" }),
  );

  const pending = (task.approvals || []).filter((item) => item.status === "pending");
  $("approvals").replaceChildren(
    ...(pending.length
      ? pending.map((approval) => {
          const el = document.createElement("div");
          el.className = "approval";
          el.innerHTML = `
            <strong>${escapeHtml(approval.operation)}</strong>
            <p>${escapeHtml(approval.reason || "")}</p>
            <small>${escapeHtml(approval.impact || "")}</small>
            <div class="actions">
              <button data-approve="true">通过</button>
              <button data-approve="false" class="secondary">拒绝</button>
            </div>
          `;
          el.querySelectorAll("button").forEach((button) => {
            button.addEventListener("click", () =>
              post("task/approval", {
                umo: task.umo,
                approval_id: approval.approval_id,
                approved: button.dataset.approve === "true",
              }),
            );
          });
          return el;
        })
      : [row("暂无待审批", "危险操作会在这里出现")]),
  );
}

await bridge.ready();
await load();

$("refresh").addEventListener("click", load);
$("save-agent").addEventListener("click", async () => {
  currentAgent.enabled = $("agent-enabled").checked;
  currentAgent.name = $("agent-name").value.trim() || "Agent";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.memory_policy ||= {};
  currentAgent.approval_policy ||= {};
  currentAgent.heartbeat_policy ||= {};
  currentAgent.memory_policy.mode = $("memory-mode").value;
  currentAgent.approval_policy.mode = $("approval-mode").value;
  currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").checked;
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
