/**
 * Reactive state store, 10s silent live polling, dirty-form & active-input
 * focus protection, XSS-safe escaping, and API action helpers for Agent Lab Classic WebUI.
 */
import {
  apiGet,
  apiPost,
  getAuthToken,
  isEmbeddedBridge,
  requestResize,
  setAuthToken,
} from "./api.js?v=1.0.0-r2";

const POLL_INTERVAL_MS = 10000;

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function fmtBytes(bytes) {
  const n = Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let val = n;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return `${val >= 100 || idx === 0 ? Math.round(val) : val.toFixed(1)} ${units[idx]}`;
}

export function fmtNum(n) {
  const v = Number(n || 0);
  return Number.isFinite(v) ? v.toLocaleString("zh-CN") : "0";
}

export function fmtDuration(startIso, endIso = "") {
  if (!startIso) return "0s";
  const start = Date.parse(startIso);
  if (!Number.isFinite(start)) return "0s";
  const end = endIso ? Date.parse(endIso) : Date.now();
  const sec = Math.max(0, Math.floor(((Number.isFinite(end) ? end : Date.now()) - start) / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  if (min < 60) return `${min}m ${rem}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}

export function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function statusLabel(status) {
  const map = {
    running: "运行中",
    paused: "已暂停",
    completed: "已完成",
    cancelled: "已停止",
  };
  return map[status] || status || "未知";
}

export function phaseLabel(phase) {
  const map = {
    planning: "只读探索规划",
    executing: "隔离执行中",
    completed: "已交付归档",
    cancelled: "已终止",
  };
  return map[phase] || phase || "-";
}

export function waitReasonLabel(reason) {
  const map = {
    "": "",
    need_plan_approval: "待审批计划",
    need_tool_approval: "待审批操作",
    need_answer: "待回答提问",
    unknown_call: "待核对中断调用",
    human_paused: "人工暂停",
    recovered_pause: "重启安全暂停",
    budget: "预算上限暂停",
    guard_paused: "防空转守卫暂停",
    tick_error: "执行异常暂停",
  };
  return map[reason || ""] ?? reason;
}

export function modeLabel(mode) {
  const map = {
    readonly: "只读 (readonly)",
    standard: "标准 (standard)",
    full: "全权限 (full)",
  };
  return map[mode] || mode || "standard";
}

export function taskPendingInfo(task, unknownCalls = null) {
  if (!task) return { approvals: 0, questions: 0, unknown: 0, total: 0 };
  const approvals =
    typeof task.pending_approvals === "number"
      ? task.pending_approvals
      : (task.approvals || []).filter((a) => a.status === "pending").length;
  const questions =
    typeof task.pending_questions === "number"
      ? task.pending_questions
      : (task.questions || []).filter((q) => q.status === "pending").length;
  const unknown = Array.isArray(unknownCalls)
    ? unknownCalls.length
    : typeof task.unknown_calls === "number"
      ? task.unknown_calls
      : task.wait_reason === "unknown_call"
        ? 1
        : 0;
  return {
    approvals,
    questions,
    unknown,
    total: approvals + questions + unknown,
  };
}

class AgentLabUIStore {
  constructor() {
    this.viewListeners = new Set();

    // 3 primary routes: projects | profiles | settings
    this.route = "projects";
    this.selectedProjectId = "";
    this.selectedTaskId = "";
    this.projectTab = "tasks"; // tasks | summary | settings
    this.settingsTab = "identity"; // identity | vault | storage
    this.selectedProfileId = "";
    this.projectSearch = "";
    this.profileSearch = "";
    this.vaultFilter = "all"; // all | secret | personal
    this.expandedProjects = new Set();

    this.loading = true;
    this.refreshing = false;
    this.error = "";
    this.authRequired = false;
    this.health = null;

    this.state = {
      version: "1.0.0",
      preview_mode: false,
      projects: [],
      tasks: [],
      profiles: [],
      credentials: [],
      preferences: { default_bot: "", progress: {} },
      identities: [],
      plugins: [],
      storage: { total_projects: 0, total_tasks: 0, total_bytes: 0, projects: [] },
      active_tasks: {},
    };

    this.taskDetails = new Map();
    this.dirtyScopes = new Set();
    this.pendingSilentRender = false;
    this.modalOpenCount = 0;
    this.pollTimer = null;
    this.pollInFlight = false;
    this._mutationSeq = 0;
  }

  // ── Subscriptions ──────────────────────────────────────────────────────────

  subscribeView(fn) {
    this.viewListeners.add(fn);
    return () => this.viewListeners.delete(fn);
  }

  notifyView(reason = "update") {
    for (const fn of this.viewListeners) {
      try {
        fn({ reason, store: this });
      } catch (e) {
        console.error(e);
      }
    }
    requestResize();
  }

  // ── Dirty Form / Focus / Modal Protection ──────────────────────────────────

  markDirty(scope) {
    if (scope) this.dirtyScopes.add(String(scope));
  }

  clearDirty(scope) {
    if (!scope) {
      this.dirtyScopes.clear();
    } else {
      this.dirtyScopes.delete(String(scope));
    }
    if (this.pendingSilentRender && !this.shouldDeferViewRender()) {
      this.pendingSilentRender = false;
      this.notifyView("deferred-flush");
    }
  }

  isDirty(scope) {
    return scope ? this.dirtyScopes.has(String(scope)) : this.dirtyScopes.size > 0;
  }

  setModalOpen(isOpen) {
    if (isOpen) {
      this.modalOpenCount += 1;
    } else {
      this.modalOpenCount = Math.max(0, this.modalOpenCount - 1);
      if (this.modalOpenCount === 0 && this.pendingSilentRender && !this.shouldDeferViewRender()) {
        this.pendingSilentRender = false;
        this.notifyView("deferred-flush");
      }
    }
  }

  isModalOpen() {
    if (this.modalOpenCount > 0) return true;
    const modalRoot = document.getElementById("modal-root");
    return Boolean(modalRoot && modalRoot.children.length > 0);
  }

  isFormFocusedInView() {
    const active = document.activeElement;
    if (!active) return false;
    const tag = active.tagName;
    const isInput =
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      tag === "SELECT" ||
      active.isContentEditable;
    if (!isInput) return false;
    const viewEl = document.getElementById("view");
    const modalEl = document.getElementById("modal-root");
    return Boolean((viewEl && viewEl.contains(active)) || (modalEl && modalEl.contains(active)));
  }

  shouldDeferViewRender() {
    if (this.isModalOpen()) return true;
    if (this.isFormFocusedInView()) return true;
    if (this.dirtyScopes.size > 0) {
      const activeDirty = document.querySelector("#view [data-dirty-scope]");
      if (activeDirty) {
        const sc = activeDirty.getAttribute("data-dirty-scope");
        if (sc && this.dirtyScopes.has(sc)) return true;
      }
      if (
        this.route === "projects" &&
        (this.dirtyScopes.has("summary") ||
          this.dirtyScopes.has("project-settings") ||
          this.dirtyScopes.has("task-inputs"))
      ) {
        return true;
      }
      if (this.route === "profiles" && this.dirtyScopes.has("profile")) {
        return true;
      }
      if (this.route === "settings" && this.dirtyScopes.has("settings")) {
        return true;
      }
    }
    return false;
  }

  flushDeferredRenderIfReady() {
    if (this.pendingSilentRender && !this.shouldDeferViewRender()) {
      this.pendingSilentRender = false;
      this.notifyView("deferred-flush");
    }
  }

  // ── Lifecycle & 10s Live Polling ───────────────────────────────────────────

  async init() {
    this.startPolling();
    document.addEventListener("focusout", () => {
      setTimeout(() => this.flushDeferredRenderIfReady(), 60);
    });
    await this.refreshAll({ silent: false });
  }

  startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => {
      if (document.hidden) return;
      this.refreshAll({ silent: true });
    }, POLL_INTERVAL_MS);
  }

  _normalizePreferences(rawPrefs) {
    if (!rawPrefs || typeof rawPrefs !== "object") {
      return { default_bot: "", progress: {} };
    }
    return {
      default_bot: String(rawPrefs.default_bot || ""),
      progress:
        rawPrefs.progress && typeof rawPrefs.progress === "object"
          ? rawPrefs.progress
          : {},
    };
  }

  _upsertProject(proj) {
    if (!proj || !proj.project_id) return;
    const list = [...(this.state.projects || [])];
    const idx = list.findIndex((p) => p.project_id === proj.project_id);
    if (idx >= 0) {
      list[idx] = { ...list[idx], ...proj };
    } else {
      list.unshift(proj);
    }
    this.state.projects = list;
  }

  _upsertProfile(prof) {
    if (!prof || !prof.profile_id) return;
    let list = [...(this.state.profiles || [])];
    if (prof.is_default) {
      list = list.map((p) =>
        p.profile_id === prof.profile_id ? p : { ...p, is_default: false }
      );
    }
    const idx = list.findIndex((p) => p.profile_id === prof.profile_id);
    if (idx >= 0) {
      list[idx] = { ...list[idx], ...prof };
    } else {
      list.push(prof);
    }
    if (list.length && !list.some((p) => p.is_default)) {
      list[0] = { ...list[0], is_default: true };
    }
    this.state.profiles = list;
  }

  _upsertCredential(cred) {
    if (!cred || !cred.credential_id) return;
    const list = [...(this.state.credentials || [])];
    const idx = list.findIndex((c) => c.credential_id === cred.credential_id);
    if (idx >= 0) {
      list[idx] = { ...list[idx], ...cred };
    } else {
      list.push(cred);
    }
    this.state.credentials = list;
  }

  _normalizeState(raw) {
    const s = raw && typeof raw === "object" ? raw : {};
    const projects = Array.isArray(s.projects) ? s.projects : [];
    const tasks = Array.isArray(s.tasks) ? s.tasks : [];
    const profiles = Array.isArray(s.profiles) ? s.profiles : [];
    const credentials = Array.isArray(s.credentials) ? s.credentials : [];
    const identities = Array.isArray(s.identities)
      ? s.identities
      : Array.isArray(s.bots)
        ? s.bots
        : [];
    const preferences = this._normalizePreferences(s.preferences);

    const storage =
      s.storage && typeof s.storage === "object"
        ? s.storage
        : { total_projects: projects.length, total_tasks: tasks.length, total_bytes: 0, projects: [] };

    return {
      version: String(s.version || "1.0.0"),
      preview_mode: Boolean(s.preview_mode),
      projects,
      tasks,
      profiles,
      credentials,
      preferences,
      identities,
      plugins: Array.isArray(s.plugins) ? s.plugins : [],
      storage,
      active_tasks: s.active_tasks && typeof s.active_tasks === "object" ? s.active_tasks : {},
    };
  }

  async refreshAll({ silent = false } = {}) {
    if (silent && this.pollInFlight) return;
    if (silent) this.pollInFlight = true;
    else this.refreshing = true;

    const reqSeq = this._mutationSeq;

    if (!silent && this.loading) {
      this.notifyView("loading");
    }

    try {
      const raw = await apiGet("/api/v1/state");
      if (reqSeq !== this._mutationSeq) {
        return;
      }
      this.state = this._normalizeState(raw);
      this.error = "";
      this.authRequired = false;
      this.loading = false;

      if (this.selectedProjectId && !this.getProject(this.selectedProjectId)) {
        this.selectedProjectId = "";
        this.selectedTaskId = "";
      }
      if (this.selectedProfileId && !this.getProfile(this.selectedProfileId)) {
        this.selectedProfileId = "";
      }

      if (this.selectedTaskId) {
        try {
          await this.loadTaskDetail(this.selectedTaskId, { notify: false });
        } catch {
          /* task might have been removed */
        }
      }

      this.refreshing = false;
      this.pollInFlight = false;

      if (silent && this.shouldDeferViewRender()) {
        this.pendingSilentRender = true;
        this.notifyView("chrome-only");
      } else {
        this.pendingSilentRender = false;
        this.notifyView(silent ? "silent-refresh" : "refresh");
      }
    } catch (err) {
      this.loading = false;
      this.refreshing = false;
      this.pollInFlight = false;
      this.error = err?.message || "无法连接 Agent Lab 后端";
      this.authRequired = err?.code === "AUTH_REQUIRED";
      this.notifyView(silent ? "chrome-only" : "error");
    } finally {
      this.refreshing = false;
      this.pollInFlight = false;
    }
  }

  async checkHealth() {
    try {
      this.health = await apiGet("/api/v1/health");
      return this.health;
    } catch (err) {
      return { ok: false, error: err?.message || "健康检查失败" };
    }
  }

  // ── Selectors & Helpers ────────────────────────────────────────────────────

  getProject(projectId) {
    return this.state.projects.find((p) => p.project_id === projectId) || null;
  }

  getTasksForProject(projectId) {
    return this.state.tasks
      .filter((t) => t.project_id === projectId)
      .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  }

  getTask(taskId) {
    return this.taskDetails.get(taskId)?.meta || this.state.tasks.find((t) => t.task_id === taskId) || null;
  }

  getTaskDetail(taskId) {
    return this.taskDetails.get(taskId) || null;
  }

  getProfile(profileId) {
    return this.state.profiles.find((p) => p.profile_id === profileId) || null;
  }

  getBots() {
    return this.state.identities || [];
  }

  getDefaultBot() {
    const bots = this.getBots();
    const defId = this.state.preferences?.default_bot || "";
    if (!defId) return bots[0] || null;
    return (
      bots.find((b) => b.platform_id === defId || b.umo === defId) ||
      bots[0] ||
      null
    );
  }

  getPrimaryActiveTask() {
    const active = this.state.tasks.filter((t) => !["completed", "cancelled"].includes(t.status));
    if (!active.length) return null;
    const running = active.find((t) => t.status === "running");
    if (running) return running;
    const waiting = active.find((t) => taskPendingInfo(t).total > 0);
    return waiting || active[0];
  }

  isTaskActiveForUmo(task) {
    if (!task || ["completed", "cancelled"].includes(task.status)) return false;
    const activeMap = this.state.active_tasks || {};
    if (task.umo && activeMap[task.umo]) {
      return activeMap[task.umo] === task.task_id;
    }
    const sameUmo = this.state.tasks.filter(
      (t) => t.umo === task.umo && !["completed", "cancelled"].includes(t.status)
    );
    return sameUmo[0]?.task_id === task.task_id;
  }

  // ── Navigation ─────────────────────────────────────────────────────────────

  selectProfile(profileId = "") {
    this.clearDirty("profile");
    this.selectedProfileId = profileId ? String(profileId) : "";
    this.notifyView("profile-select");
  }

  setRoute(route, options = {}) {
    if (route === "profiles" && !options.profileId) {
      this.selectedProfileId = "";
    }
    return this.navigate(route, options);
  }

  navigate(route, { projectId = undefined, taskId = "", tab = "", settingsTab = "", profileId = undefined } = {}) {
    if (route === "credentials") {
      this.route = "settings";
      this.settingsTab = "vault";
    } else if (route === "storage") {
      this.route = "settings";
      this.settingsTab = "storage";
    } else {
      this.route = route || "projects";
    }

    if (settingsTab) {
      this.settingsTab = settingsTab;
    }
    if (profileId !== undefined && profileId !== null) {
      this.selectedProfileId = profileId ? String(profileId) : "";
    } else if (this.route === "profiles") {
      this.selectedProfileId = "";
    }

    if (projectId !== undefined && projectId !== null) {
      if (projectId) {
        this.selectedProjectId = projectId;
        this.expandedProjects.add(projectId);
      } else if (this.route === "projects" && !taskId && projectId === "") {
        this.selectedProjectId = "";
        this.selectedTaskId = "";
      }
    }

    if (taskId) {
      this.selectedTaskId = taskId;
      const t = this.getTask(taskId);
      if (t?.project_id) {
        this.selectedProjectId = t.project_id;
        this.expandedProjects.add(t.project_id);
      }
      this.projectTab = "tasks";
      this.loadTaskDetail(taskId, { notify: true }).catch(() => {});
    }

    if (tab) {
      this.projectTab = tab === "protection" ? "settings" : tab;
    }
    this.notifyView("navigate");
  }

  openProject(projectId, tab = "tasks") {
    this.route = "projects";
    this.selectedProjectId = projectId;
    this.expandedProjects.add(projectId);
    this.projectTab = tab === "protection" ? "settings" : tab;
    const tasks = this.getTasksForProject(projectId);
    if (this.selectedTaskId && !tasks.some((t) => t.task_id === this.selectedTaskId)) {
      this.selectedTaskId = tasks[0]?.task_id || "";
    } else if (!this.selectedTaskId && tasks.length) {
      this.selectedTaskId = tasks[0].task_id;
    }
    if (this.selectedTaskId) {
      this.loadTaskDetail(this.selectedTaskId, { notify: true }).catch(() => {});
    }
    this.notifyView("navigate");
  }

  openTask(taskId) {
    const task = this.getTask(taskId);
    this.route = "projects";
    if (task?.project_id) {
      this.selectedProjectId = task.project_id;
      this.expandedProjects.add(task.project_id);
    }
    this.selectedTaskId = taskId;
    this.projectTab = "tasks";
    this.notifyView("navigate");
    this.loadTaskDetail(taskId, { notify: true }).catch((err) => {
      this.toast(err.message || "加载任务详情失败", "error");
    });
  }

  toggleProjectExpand(projectId) {
    if (this.expandedProjects.has(projectId)) {
      this.expandedProjects.delete(projectId);
    } else {
      this.expandedProjects.add(projectId);
    }
    this.notifyView("tree-toggle");
  }

  // ── API Actions ────────────────────────────────────────────────────────────

  async workspaceAction(action, payload = {}, { refresh = true } = {}) {
    const res = await apiPost("/api/v1/workspace", { action, ...payload });
    this._mutationSeq += 1;
    if (refresh) {
      await this.refreshAll({ silent: true });
    }
    return res;
  }

  async loadTaskDetail(taskId, { notify = true } = {}) {
    if (!taskId) return null;
    const res = await apiPost("/api/v1/workspace", { action: "task_detail", task_id: taskId });
    const detail = res?.detail && typeof res.detail === "object" ? res.detail : res;
    if (detail && detail.meta) {
      this.taskDetails.set(taskId, detail);
    }
    if (notify) {
      if (this.shouldDeferViewRender()) {
        this.pendingSilentRender = true;
        this.notifyView("chrome-only");
      } else {
        this.notifyView("task-detail");
      }
    }
    return detail;
  }

  async createProject({ title, category = "通用", profile_id = "", source_umo = "", platform_id = "" }) {
    const res = await this.workspaceAction(
      "create_project",
      {
        title,
        category,
        profile_id,
        source_umo,
        platform_id,
      },
      { refresh: false }
    );
    const proj = res?.project || (res?.project_id ? res : null);
    if (proj?.project_id) {
      this._upsertProject(proj);
      this.selectedProjectId = proj.project_id;
      this.expandedProjects.add(proj.project_id);
      this.selectedTaskId = "";
      this.route = "projects";
      this.projectTab = "tasks";
    }
    this.notifyView("navigate");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async updateProject(projectId, fields) {
    this.clearDirty("project-settings");
    this.clearDirty("summary");
    const res = await this.workspaceAction(
      "update_project",
      { project_id: projectId, ...fields },
      { refresh: false }
    );
    const proj = res?.project || (res?.project_id ? res : null);
    if (proj?.project_id) {
      this._upsertProject(proj);
    }
    this.notifyView("state-patch");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async draftSummary(projectId, taskId = "") {
    return this.workspaceAction("draft_summary", { project_id: projectId, task_id: taskId }, { refresh: false });
  }

  async saveSummary(projectId, summary, taskId = "") {
    this.clearDirty("summary");
    return this.workspaceAction("save_summary", {
      project_id: projectId,
      summary,
      text: summary,
      task_id: taskId,
    });
  }

  async startTask({ goal, project_id = "", profile_id = "", constraints = [], completion_conditions = [], brief = "", umo = "" }) {
    const res = await this.workspaceAction("start_task", {
      goal,
      project_id,
      profile_id,
      constraints,
      completion_conditions,
      brief,
      umo,
    });
    const task = res.task || res;
    if (task?.task_id) {
      this.openTask(task.task_id);
    }
    return res;
  }

  async activateTask(taskId) {
    return this.workspaceAction("activate_task", { task_id: taskId });
  }

  async moveTask(taskId, projectId) {
    const res = await this.workspaceAction("move_task", { task_id: taskId, project_id: projectId });
    this.selectedProjectId = projectId;
    this.expandedProjects.add(projectId);
    this.notifyView("navigate");
    return res;
  }

  async pauseTask(taskId, reason = "") {
    return this.workspaceAction("pause_task", { task_id: taskId, reason });
  }

  async resumeTask(taskId) {
    return this.workspaceAction("resume_task", { task_id: taskId });
  }

  async stopTask(taskId, reason = "") {
    return this.workspaceAction("stop_task", { task_id: taskId, reason });
  }

  async deliverTask(taskId, note = "") {
    return this.workspaceAction("deliver_task", { task_id: taskId, note });
  }

  async approve(taskId, approvalId, decision, note = "") {
    this.clearDirty("task-inputs");
    return this.workspaceAction("approve", {
      task_id: taskId,
      approval_id: approvalId,
      decision,
      note,
    });
  }

  async answer(taskId, questionId, answer) {
    this.clearDirty("task-inputs");
    return this.workspaceAction("answer", {
      task_id: taskId,
      question_id: questionId,
      answer,
    });
  }

  async steer(taskId, guidance) {
    this.clearDirty("task-inputs");
    return this.workspaceAction("steer", {
      task_id: taskId,
      guidance,
    });
  }

  async reconcile(taskId, callId, status, note = "") {
    return this.workspaceAction("reconcile", {
      task_id: taskId,
      call_id: callId,
      status,
      note,
    });
  }

  async updateBudget(taskId, budget) {
    return this.workspaceAction("update_budget", {
      task_id: taskId,
      budget,
    });
  }

  async readRecord(relPath, taskId = "") {
    return this.workspaceAction("read_record", { rel_path: relPath, task_id: taskId }, { refresh: false });
  }

  async cleanupPreview(scope, { project_id = "", task_id = "" } = {}) {
    return this.workspaceAction("cleanup_preview", { scope, project_id, task_id }, { refresh: false });
  }

  async cleanupConfirm(token) {
    const res = await this.workspaceAction("cleanup_confirm", { token }, { refresh: true });
    if (this.selectedTaskId && !this.getTask(this.selectedTaskId)) {
      this.selectedTaskId = "";
    }
    if (this.selectedProjectId && !this.getProject(this.selectedProjectId)) {
      this.selectedProjectId = "";
      this.selectedTaskId = "";
    }
    this.notifyView("cleanup");
    return res;
  }

  async setDefaultBot(platformId) {
    const prevPrefs = JSON.parse(
      JSON.stringify(this.state.preferences || { default_bot: "", progress: {} })
    );
    this.state.preferences = {
      ...prevPrefs,
      default_bot: String(platformId || ""),
    };
    this.notifyView("state-patch");
    try {
      const res = await apiPost("/api/v1/workspace", {
        action: "set_default_bot",
        platform_id: platformId,
      });
      this._mutationSeq += 1;
      if (res?.preferences && typeof res.preferences === "object") {
        this.state.preferences = this._normalizePreferences(res.preferences);
      }
      this.notifyView("state-patch");
      return res;
    } catch (err) {
      this.state.preferences = prevPrefs;
      this.notifyView("state-patch");
      throw err;
    }
  }

  async setProgress({ umo = "", enabled = true, min_interval_seconds = 30 }) {
    this.clearDirty("settings");
    const key = String(umo || "").trim();
    const prevPrefs = JSON.parse(
      JSON.stringify(this.state.preferences || { default_bot: "", progress: {} })
    );
    const nextProgress = { ...(prevPrefs.progress || {}) };
    if (key) {
      const existing =
        nextProgress[key] && typeof nextProgress[key] === "object" ? nextProgress[key] : {};
      nextProgress[key] = {
        ...existing,
        enabled: Boolean(enabled),
        min_interval_seconds: Number(min_interval_seconds ?? 30),
      };
    } else {
      nextProgress.enabled = Boolean(enabled);
      nextProgress.min_interval_seconds = Number(min_interval_seconds ?? 30);
    }
    this.state.preferences = {
      ...prevPrefs,
      progress: nextProgress,
    };
    this.notifyView("state-patch");

    try {
      const res = await apiPost("/api/v1/workspace", {
        action: "set_progress",
        umo,
        enabled,
        min_interval_seconds,
      });
      this._mutationSeq += 1;
      if (res?.preferences && typeof res.preferences === "object") {
        this.state.preferences = this._normalizePreferences(res.preferences);
      }
      this.notifyView("state-patch");
      return res;
    } catch (err) {
      this.state.preferences = prevPrefs;
      this.notifyView("state-patch");
      throw err;
    }
  }

  async saveProfile(profileData, { select = true } = {}) {
    this.clearDirty("profile");
    const res = await apiPost("/api/v1/profiles", {
      action: "save",
      ...profileData,
      profile: profileData,
    });
    this._mutationSeq += 1;
    const saved = res?.profile || (res?.profile_id ? res : null);
    if (saved?.profile_id) {
      this._upsertProfile(saved);
      if (select) {
        this.selectedProfileId = saved.profile_id;
      }
    }
    this.notifyView("profile-saved");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async duplicateProfile(profileId, name = "", { select = true } = {}) {
    this.clearDirty("profile");
    const res = await apiPost("/api/v1/profiles", {
      action: "duplicate",
      profile_id: profileId,
      name,
    });
    this._mutationSeq += 1;
    const cloned = res?.profile || (res?.profile_id ? res : null);
    if (cloned?.profile_id) {
      this._upsertProfile(cloned);
      if (select) {
        this.selectedProfileId = cloned.profile_id;
      }
    }
    this.notifyView("profile-saved");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async deleteProfile(profileId) {
    this.clearDirty("profile");
    const res = await apiPost("/api/v1/profiles", {
      action: "delete",
      profile_id: profileId,
    });
    this._mutationSeq += 1;
    const remaining = (this.state.profiles || []).filter((p) => p.profile_id !== profileId);
    if (remaining.length && !remaining.some((p) => p.is_default)) {
      remaining[0] = { ...remaining[0], is_default: true };
    }
    const newDefaultId =
      remaining.find((p) => p.is_default)?.profile_id || remaining[0]?.profile_id || "";
    this.state.profiles = remaining;
    if (newDefaultId) {
      this.state.projects = (this.state.projects || []).map((proj) =>
        proj.profile_id === profileId ? { ...proj, profile_id: newDefaultId } : proj
      );
    }
    if (this.selectedProfileId === profileId) {
      this.selectedProfileId = "";
    }
    this.notifyView("profile-deleted");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async saveCredential(credData) {
    const res = await apiPost("/api/v1/credentials", {
      action: "save",
      ...credData,
      credential: credData,
    });
    this._mutationSeq += 1;
    const saved = res?.credential || (res?.credential_id ? res : null);
    if (saved?.credential_id) {
      this._upsertCredential(saved);
    }
    this.notifyView("state-patch");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  async deleteCredential(credentialId) {
    const res = await apiPost("/api/v1/credentials", {
      action: "delete",
      credential_id: credentialId,
    });
    this._mutationSeq += 1;
    this.state.credentials = (this.state.credentials || []).filter(
      (c) => c.credential_id !== credentialId
    );
    this.notifyView("state-patch");
    this.refreshAll({ silent: true }).catch(() => {});
    return res;
  }

  setTokenAndReconnect(token) {
    setAuthToken(token);
    return this.refreshAll({ silent: false });
  }

  getToken() {
    return getAuthToken();
  }

  isStandalone() {
    return !isEmbeddedBridge();
  }

  // ── Toast Feedback ─────────────────────────────────────────────────────────

  toast(message, tone = "info") {
    const root = document.getElementById("toast-root");
    if (!root) return;
    const el = document.createElement("div");
    el.className = `al-toast al-toast-${tone}`;
    el.textContent = String(message || "");
    root.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 180);
    }, 3200);
  }
}

export const store = new AgentLabUIStore();
