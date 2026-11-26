/**
 * Unified Cold-Minimalist Classic WebUI for Agent Lab v1.0.0.
 * Pure vanilla ES module with AbortController cleanup, XSS-safe esc(),
 * zero native dialogs, and 100% API alignment with WebUIController.
 */
import {
  esc,
  fmtBytes,
  fmtDuration,
  fmtNum,
  fmtTime,
  modeLabel,
  phaseLabel,
  statusLabel,
  taskPendingInfo,
  waitReasonLabel,
} from "./store.js?v=1.0.0";
import { requestResize } from "./api.js?v=1.0.0";

const NAV_ITEMS = [
  { id: "projects", label: "项目与任务" },
  { id: "profiles", label: "方案管理" },
  { id: "settings", label: "系统设置" },
];

const PROVIDER_LABELS = {
  github: "GitHub",
  ssh: "SSH",
  npm: "npm",
  pypi: "PyPI",
  openai: "LLM/API",
  generic: "通用",
};

const FOLDER_SVG = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h3l1.3 1.5h4.7A1.5 1.5 0 0 1 14 6v5.5A1.5 1.5 0 0 1 12.5 13h-9A1.5 1.5 0 0 1 2 11.5V4.5Z"/></svg>`;
const BOT_SVG = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="4.5" width="11" height="8" rx="2"/><path d="M8 2v2.5M6 8.5h.01M10 8.5h.01M5.5 10.7h5"/></svg>`;
const PLUGIN_FALLBACK_SVG = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 2.5v2.5M10 2.5v2.5M4 5h8v3.2a4 4 0 0 1-8 0V5ZM8 12.2v1.8"/></svg>`;
const CHEVRON_SVG = `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 4 4 4-4 4"/></svg>`;
const SHIELD_SVG = `<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.8 13 3.8v4.1c0 3.1-2.1 5.3-5 6.3-2.9-1-5-3.2-5-6.3V3.8L8 1.8Z"/></svg>`;
const SLIDERS_SVG = `<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/><circle cx="5.5" cy="4.5" r="1.3" fill="#f6f6f7"/><circle cx="10.5" cy="8" r="1.3" fill="#f6f6f7"/><circle cx="6.5" cy="11.5" r="1.3" fill="#f6f6f7"/></svg>`;
const COMPASS_SVG = `<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#4c525a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6"/><polygon points="10.3,5.7 8.9,8.9 5.7,10.3 7.1,7.1" fill="none"/></svg>`;

function profileModeIcon(mode) {
  if (mode === "readonly") return SHIELD_SVG;
  if (mode === "full") return COMPASS_SVG;
  return SLIDERS_SVG;
}

function profileModeBadgeLabel(mode) {
  if (mode === "readonly") return "只读模式";
  if (mode === "full") return "全权限";
  return "标准保护";
}

export function mountClassicView(store) {
  const ac = new AbortController();
  const { signal } = ac;

  const shellEl = document.getElementById("main-app");
  const statusBarEl = document.getElementById("global-status-bar");
  const railEl = document.getElementById("app-rail");
  const viewEl = document.getElementById("view");
  const navEl = document.getElementById("nav");
  const treeEl = document.getElementById("project-sidebar");
  const storageBarEl = document.getElementById("rail-storage");
  const feedbackEl = document.getElementById("feedback");
  const modalRoot = document.getElementById("modal-root");
  const botPopover = document.getElementById("bot-switcher-popover");
  const agentSwitcherBtn = document.getElementById("agent-switcher-btn");
  const mobileBackdrop = document.getElementById("mobile-rail-backdrop");

  let runtimeTicker = null;
  let profileDraft = null;
  let profileDraftId = "";

  // ── Scroll, <details> & Cursor Preservation ───────────────────────────────

  function captureViewState() {
    const scrolls = [];
    document.querySelectorAll("#main-scroll, #project-sidebar, [data-scroll-key]").forEach((el) => {
      const key = el.id || el.getAttribute("data-scroll-key");
      if (key) scrolls.push({ key, top: el.scrollTop, left: el.scrollLeft });
    });
    const openDetails = [];
    viewEl?.querySelectorAll("details[data-detail-key][open]").forEach((el) => {
      openDetails.push(el.getAttribute("data-detail-key"));
    });
    const activeEl = document.activeElement;
    const focusInfo =
      activeEl && viewEl?.contains(activeEl) && activeEl.id
        ? { id: activeEl.id, start: activeEl.selectionStart, end: activeEl.selectionEnd }
        : null;
    return { scrolls, openDetails, focusInfo };
  }

  function restoreViewState(snap) {
    if (!snap) return;
    for (const key of snap.openDetails) {
      const el = viewEl?.querySelector(`details[data-detail-key="${CSS.escape(key)}"]`);
      if (el) el.open = true;
    }
    for (const s of snap.scrolls) {
      const el =
        document.getElementById(s.key) ||
        document.querySelector(`[data-scroll-key="${CSS.escape(s.key)}"]`);
      if (el) {
        el.scrollTop = s.top;
        el.scrollLeft = s.left;
      }
    }
    if (snap.focusInfo) {
      const target = document.getElementById(snap.focusInfo.id);
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
        if (typeof snap.focusInfo.start === "number" && typeof target.setSelectionRange === "function") {
          try {
            target.setSelectionRange(snap.focusInfo.start, snap.focusInfo.end);
          } catch {
            /* ignore */
          }
        }
      }
    }
  }

  // ── Top Status Bar & Left Sidebar ────────────────────────────────────────

  function renderTopBar() {
    const bot = store.getDefaultBot();
    const nameEl = document.getElementById("current-agent-name");
    const instEl = document.getElementById("identity-instance");
    if (nameEl) nameEl.textContent = bot ? bot.display_name || bot.name || bot.platform_id : "Agent Lab";
    if (instEl) instEl.textContent = bot?.platform_id || "";

    const activeTask = store.getPrimaryActiveTask();
    const dotEl = document.getElementById("status-dot");
    const textEl = document.getElementById("status-text");
    const taskEl = document.getElementById("status-task");
    const taskIdEl = document.getElementById("current-task-id");
    const runtimeEl = document.getElementById("task-runtime");
    const viewBtn = document.getElementById("status-view-btn");

    if (activeTask) {
      const pend = taskPendingInfo(activeTask);
      const isWait = activeTask.status === "paused" || pend.total > 0;
      if (dotEl) dotEl.className = `status-dot ${isWait ? "waiting" : activeTask.status}`;
      if (textEl) {
        const wr = waitReasonLabel(activeTask.wait_reason);
        textEl.textContent = wr || statusLabel(activeTask.status);
      }
      if (taskEl) taskEl.hidden = false;
      if (taskIdEl) taskIdEl.textContent = activeTask.task_id;
      if (runtimeEl) runtimeEl.textContent = fmtDuration(activeTask.started_at, activeTask.ended_at);
      if (viewBtn) {
        viewBtn.hidden = false;
        viewBtn.dataset.taskId = activeTask.task_id;
      }
    } else {
      if (dotEl) dotEl.className = "status-dot idle";
      if (textEl) textEl.textContent = "空闲";
      if (taskEl) taskEl.hidden = true;
      if (viewBtn) viewBtn.hidden = true;
    }

    const refreshBtn = document.getElementById("refresh-btn");
    if (refreshBtn) {
      refreshBtn.classList.toggle("spinning", store.refreshing);
    }

    if (botPopover && !botPopover.hidden) {
      renderBotPopover();
    }
  }

  function renderBotPopover() {
    if (!botPopover) return;
    const bots = store.getBots();
    const defId = store.state.preferences?.default_bot || "";
    if (!bots.length) {
      botPopover.innerHTML = `<div class="cl-hint" style="padding:8px 10px;">未检测到多机器人实例，任务仍可通过当前会话启动。</div>`;
      return;
    }
    botPopover.innerHTML = bots
      .map((b) => {
        const idVal = b.platform_id || b.umo || "";
        const isDef =
          (defId && (b.platform_id === defId || b.umo === defId)) ||
          (!defId && bots[0] === b);
        return `
          <button type="button" class="bot-pop-item ${isDef ? "active" : ""}" data-select-bot="${esc(idVal)}">
            <span>${esc(b.display_name || b.name || idVal)}</span>
            <small>${isDef ? "当前默认" : esc(b.platform_id || b.umo)}</small>
          </button>
        `;
      })
      .join("");
  }

  function renderSidebar() {
    if (navEl) {
      const pendingAll = store.state.tasks.reduce((acc, t) => acc + taskPendingInfo(t).total, 0);
      navEl.innerHTML = NAV_ITEMS.map((item) => {
        const active = store.route === item.id;
        let countHtml = "";
        if (item.id === "projects" && pendingAll > 0) {
          countHtml = `<span class="nav-count">${pendingAll} 待处理</span>`;
        } else if (item.id === "profiles") {
          countHtml = `<span class="nav-count">${store.state.profiles.length}</span>`;
        }
        return `<button type="button" class="${active ? "active" : ""}" data-nav="${esc(item.id)}"><strong>${esc(item.label)}</strong>${countHtml}</button>`;
      }).join("");
    }

    if (treeEl) {
      const projects = store.state.projects || [];
      let html = `
        <div class="project-tree-head">
          <span>项目列表</span>
          <button type="button" data-action="open-create-project">+ 新建</button>
        </div>
      `;
      if (!projects.length) {
        html += `<div class="project-tree-empty">暂无项目，可点击「+ 新建」创建。</div>`;
      } else {
        for (const p of projects) {
          const pTasks = store.getTasksForProject(p.project_id);
          const isExp = store.expandedProjects.has(p.project_id);
          const isSel = store.route === "projects" && store.selectedProjectId === p.project_id;
          html += `
            <div class="project-tree-node">
              <div class="project-tree-row ${isSel ? "selected" : ""}">
                <button type="button" class="project-chevron ${isExp ? "open" : ""}" data-toggle-project="${esc(p.project_id)}" aria-label="展开或收起项目">
                  ${CHEVRON_SVG}
                </button>
                <button type="button" class="project-tree-title" data-open-project="${esc(p.project_id)}">
                  ${FOLDER_SVG}
                  <span>${esc(p.title)}</span>
                  <small>${pTasks.length}</small>
                </button>
              </div>
              <div class="project-tree-children ${isExp ? "open" : ""}">
                ${pTasks
                  .map((t) => {
                    const detail = store.getTaskDetail(t.task_id);
                    const pend = taskPendingInfo(t, detail?.unknown_calls);
                    const tSel = isSel && store.selectedTaskId === t.task_id;
                    let mark = "";
                    if (pend.approvals > 0 || pend.unknown > 0) {
                      mark = `<span class="tree-pending-mark danger" title="待审批或异常核对">!</span>`;
                    } else if (pend.questions > 0) {
                      mark = `<span class="tree-pending-mark" title="待回答提问">?</span>`;
                    }
                    return `
                      <button type="button" class="project-tree-task ${tSel ? "selected" : ""}" data-open-task="${esc(t.task_id)}">
                        <span class="project-dot ${esc(t.status)}"></span>
                        <span class="project-tree-task-label">${esc(t.goal || t.task_id)}</span>
                        ${mark}
                      </button>
                    `;
                  })
                  .join("")}
              </div>
            </div>
          `;
        }
      }
      treeEl.innerHTML = html;
    }

    if (storageBarEl) {
      const totalBytes = store.state.storage?.total_bytes || 0;
      storageBarEl.innerHTML = `
        <button type="button" class="rail-storage-btn" data-nav="storage">
          <span>存储占用</span>
          <strong>${esc(fmtBytes(totalBytes))}</strong>
        </button>
      `;
    }
  }

  function renderFeedback() {
    if (!feedbackEl) return;
    if (store.error) {
      feedbackEl.hidden = false;
      feedbackEl.className = "feedback error";
      feedbackEl.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
          <span>${esc(store.error)}</span>
          <div class="cl-actions">
            ${store.authRequired ? `<button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-action="open-token-modal">填写访问令牌</button>` : ""}
            <button type="button" class="cl-btn cl-btn-sm" data-action="retry-connect">重试连接</button>
          </div>
        </div>
      `;
    } else if (store.loading) {
      feedbackEl.hidden = false;
      feedbackEl.className = "feedback";
      feedbackEl.textContent = "正在连接 Agent Lab 控制台...";
    } else {
      feedbackEl.hidden = true;
    }
  }

  // ── Route 1: Projects Overview & Project Detail ──────────────────────────

  function renderProjectsOverview() {
    const projects = store.state.projects || [];
    const tasks = store.state.tasks || [];
    const totalBytes = store.state.storage?.total_bytes || 0;
    const q = (store.projectSearch || "").trim().toLowerCase();
    const filtered = projects.filter((p) => {
      if (!q) return true;
      return (
        (p.title || "").toLowerCase().includes(q) ||
        (p.category || "").toLowerCase().includes(q) ||
        (p.summary || "").toLowerCase().includes(q)
      );
    });

    return `
      <div>
        <div class="cl-header">
          <div>
            <h1>项目与任务</h1>
            <p class="cl-subtitle">按项目隔离工作区、执行方案与任务上下文轨迹。</p>
          </div>
          <div class="cl-actions">
            <button type="button" class="cl-btn cl-btn-primary" data-action="open-create-project">+ 新建项目</button>
          </div>
        </div>

        <div class="project-hero-strip">
          <div><strong>${projects.length}</strong><span>项目数</span></div>
          <div><strong>${tasks.length}</strong><span>任务记录</span></div>
          <div><strong>${esc(fmtBytes(totalBytes))}</strong><span>磁盘占用</span></div>
        </div>

        <div class="project-toolbar">
          <input
            id="proj-search-input"
            type="search"
            class="cl-input project-search-input"
            placeholder="搜索项目名称、分类或摘要..."
            value="${esc(store.projectSearch)}"
          />
        </div>

        ${
          !filtered.length
            ? `<div class="cl-empty">
                <p>${projects.length ? "未找到匹配的项目。" : "当前还没有项目，创建一个项目以开始长周期任务。"}</p>
                ${!projects.length ? `<button type="button" class="cl-btn cl-btn-primary" data-action="open-create-project">+ 新建第一个项目</button>` : ""}
              </div>`
            : `<div class="project-folder-grid">
                ${filtered
                  .map((p) => {
                    const pTasks = store.getTasksForProject(p.project_id);
                    const runCount = typeof p.running_count === "number" ? p.running_count : pTasks.filter((t) => t.status === "running").length;
                    const pendCount = typeof p.pending_count === "number" ? p.pending_count : pTasks.reduce((s, t) => s + taskPendingInfo(t).total, 0);
                    const summaryText = (p.summary || "").trim() || "暂无项目摘要。";
                    return `
                      <button type="button" class="project-folder-card" data-open-project="${esc(p.project_id)}">
                        <div class="project-folder-top">
                          <span class="project-folder-icon">${FOLDER_SVG}</span>
                          <span class="project-cat-tag">${esc(p.category || "通用")}</span>
                        </div>
                        <div class="project-folder-title">${esc(p.title)}</div>
                        <p class="project-folder-desc">${esc(summaryText)}</p>
                        <div class="project-folder-foot">
                          <span>${pTasks.length} 个任务</span>
                          <span>
                            ${runCount > 0 ? `<span class="has-running">${runCount} 运行中</span>` : ""}
                            ${runCount > 0 && pendCount > 0 ? " · " : ""}
                            ${pendCount > 0 ? `<span class="has-pending">${pendCount} 待处理</span>` : ""}
                            ${runCount === 0 && pendCount === 0 ? esc(fmtTime(p.updated_at)) : ""}
                          </span>
                        </div>
                      </button>
                    `;
                  })
                  .join("")}
              </div>`
        }
      </div>
    `;
  }

  function renderProjectDetail(project) {
    const tab = store.projectTab || "tasks";
    return `
      <div>
        <div class="cl-header">
          <div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px;">
              <button type="button" class="cl-btn cl-btn-sm" data-action="back-projects">← 返回</button>
              <span class="project-cat-tag">${esc(project.category || "通用")}</span>
            </div>
            <h1>${esc(project.title)}</h1>
          </div>
          <div class="cl-actions">
            <button type="button" class="cl-btn cl-btn-primary" data-action="open-create-task" data-project-id="${esc(project.project_id)}">+ 新建任务</button>
          </div>
        </div>

        <div class="cl-tabs" role="tablist">
          <button type="button" class="cl-tab ${tab === "tasks" ? "active" : ""}" data-project-tab="tasks">任务</button>
          <button type="button" class="cl-tab ${tab === "summary" ? "active" : ""}" data-project-tab="summary">摘要与存储</button>
          <button type="button" class="cl-tab ${tab === "settings" ? "active" : ""}" data-project-tab="settings">项目设置</button>
        </div>

        ${
          tab === "tasks"
            ? renderProjectTasksTab(project)
            : tab === "summary"
              ? renderProjectSummaryTab(project)
              : renderProjectSettingsTab(project)
        }
      </div>
    `;
  }

  function renderProjectTasksTab(project) {
    const tasks = store.getTasksForProject(project.project_id);
    if (!tasks.length) {
      return `
        <div class="cl-empty">
          <p>本项目暂无任务记录，可在当前工作区启动一个隔离任务。</p>
          <button type="button" class="cl-btn cl-btn-primary" data-action="open-create-task" data-project-id="${esc(project.project_id)}">+ 新建任务</button>
        </div>
      `;
    }

    if (!store.selectedTaskId || !tasks.some((t) => t.task_id === store.selectedTaskId)) {
      store.selectedTaskId = tasks[0].task_id;
    }
    const baseTask = store.getTask(store.selectedTaskId) || tasks[0];
    const detail = store.getTaskDetail(baseTask.task_id);
    if (!detail) {
      store.loadTaskDetail(baseTask.task_id, { notify: true }).catch(() => {});
    }
    const task = detail?.meta || baseTask;

    return `
      <div class="cl-task-bar">
        <div class="cl-task-strip">
          ${tasks
            .map((t) => {
              const pend = taskPendingInfo(t, store.getTaskDetail(t.task_id)?.unknown_calls);
              const isSel = t.task_id === task.task_id;
              return `
                <button type="button" class="cl-task-pill ${isSel ? "active" : ""}" data-open-task="${esc(t.task_id)}">
                  <span class="project-dot ${esc(t.status)}"></span>
                  <span class="cl-task-pill-label">${esc(t.goal || t.task_id)}</span>
                  ${pend.total > 0 ? `<span class="cl-task-pill-meta">(${pend.total})</span>` : ""}
                </button>
              `;
            })
            .join("")}
        </div>
        <button type="button" class="cl-btn cl-btn-sm" data-action="open-create-task" data-project-id="${esc(project.project_id)}">+ 新建任务</button>
      </div>
      ${renderTaskDetailCard(task, detail)}
    `;
  }

  function renderTaskDetailCard(task, detail) {
    const isTerminal = task.status === "completed" || task.status === "cancelled";
    const isActive = store.isTaskActiveForUmo(task);
    const unknownCalls = detail?.unknown_calls || [];
    const pendingApprovals = (task.approvals || []).filter((a) => a.status === "pending");
    const resolvedApprovals = (task.approvals || []).filter((a) => a.status !== "pending");
    const pendingQuestions = (task.questions || []).filter((q) => q.status === "pending");
    const answeredQuestions = (task.questions || []).filter((q) => q.status !== "pending");
    const steps = task.steps || [];
    const doneSteps = steps.filter((s) => s.status === "completed").length;
    const totalSteps = steps.length;

    const prof = store.getProfile(task.profile_id) || detail?.profile;
    const profName = prof?.name || task.profile_id || "default";
    const permMode = task.execution_settings?.mode || prof?.permission_mode || "standard";
    const roots = task.authorized_scope_roots?.length
      ? task.authorized_scope_roots
      : task.scope_roots?.length
        ? task.scope_roots
        : task.execution_settings?.roots || [];

    const usage = task.usage || {};
    const continuity = task.execution_settings?.continuity || {};
    const budget = task.execution_settings?.budget || {};
    const ctxCap = Math.max(1, Number(continuity.context_tokens || 100000));
    const handoffPct = Number(continuity.context_percent || 55);
    const handoffThreshold = Math.round((ctxCap * handoffPct) / 100);
    const estCtx = Number(usage.last_estimated_tokens || 0);
    const ctxRatioPct = Math.min(100, Math.round((estCtx / Math.max(1, handoffThreshold)) * 100));

    // AT MOST 1 status badge in task header
    const isPositive = task.status === "running" || task.status === "completed";
    const isStopped = task.status === "cancelled";
    const statusText = waitReasonLabel(task.wait_reason) || statusLabel(task.status);
    const pillClass = isPositive ? "is-positive" : isStopped ? "is-stopped" : "";

    const metaParts = [
      task.task_id,
      profName,
      `计划 v${task.version || 0}`,
      `步骤 ${doneSteps}/${totalSteps}`,
      modeLabel(permMode),
    ];
    if (task.started_at) {
      metaParts.push(`耗时 ${fmtDuration(task.started_at, task.ended_at)}`);
    }

    const messages = detail?.messages || [];
    const journal = detail?.journal || [];
    const files = detail?.files || [];

    return `
      <div class="cl-card">
        <!-- Header: Title + 1 status pill + actions + calm subtitle line -->
        <div class="cl-task-head">
          <div style="min-width:0;flex:1;">
            <div class="cl-task-title-row">
              <h2>${esc(task.goal || task.task_id)}</h2>
              <span class="cl-status-pill ${pillClass}">
                <span class="dot" aria-hidden="true"></span>
                <span>${esc(statusText)}</span>
              </span>
            </div>
            <p class="cl-task-meta-line">${esc(metaParts.join(" · "))}</p>
          </div>
          <div class="cl-actions">
            ${!isTerminal && !isActive ? `<button type="button" class="cl-btn cl-btn-sm" data-task-action="activate" data-task-id="${esc(task.task_id)}">切换到此任务</button>` : ""}
            ${!isTerminal && task.status === "running" ? `<button type="button" class="cl-btn cl-btn-sm" data-task-action="pause" data-task-id="${esc(task.task_id)}">暂停</button>` : ""}
            ${!isTerminal && task.status === "paused" ? `<button type="button" class="cl-btn cl-btn-sm" data-task-action="resume" data-task-id="${esc(task.task_id)}">继续</button>` : ""}
            ${!isTerminal ? `<button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-task-action="deliver" data-task-id="${esc(task.task_id)}">按现状交付</button>` : ""}
            ${!isTerminal ? `<button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-task-action="stop" data-task-id="${esc(task.task_id)}">停止任务</button>` : ""}
            <button type="button" class="cl-btn cl-btn-sm" data-task-action="move" data-task-id="${esc(task.task_id)}">归入项目</button>
            ${!isTerminal ? `<button type="button" class="cl-btn cl-btn-sm" data-task-action="budget" data-task-id="${esc(task.task_id)}">调整预算</button>` : ""}
          </div>
        </div>

        <div class="cl-task-workspace-line">
          <span>工作目录：<code>${esc(task.execution_cwd || task.session_workspace_root || "会话默认工作区")}</code></span>
          <span>授权目录：${roots.length ? roots.map((r) => `<code>${esc(r)}</code>`).join(" ") : "仅会话工作区"}</span>
          ${(task.constraints || []).length ? `<span>约束：${esc(task.constraints.join("；"))}</span>` : ""}
        </div>

        <!-- Unknown Interruption Calls -->
        ${
          unknownCalls.length
            ? `<div class="cl-decision-card unknown">
                <div class="cl-decision-head">
                  <strong>异常中断调用核对 (${unknownCalls.length})</strong>
                  <span class="cl-hint">需核对实际执行结果后恢复</span>
                </div>
                <div class="cl-decision-body">
                  <p class="cl-hint">进程在以下工具调用期间发生中断，请确认其真实状态：</p>
                  ${unknownCalls
                    .map(
                      (c) => `
                    <div class="cl-unknown-item">
                      <div style="min-width:0;flex:1;">
                        <div><strong><code>${esc(c.tool_name || "unknown_tool")}</code></strong> · <span class="cl-hint">${esc(c.call_id)} · ${esc(fmtTime(c.time))}</span></div>
                        ${c.arguments ? `<pre class="cl-json-pre">${esc(JSON.stringify(c.arguments, null, 2))}</pre>` : ""}
                      </div>
                      <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-action="open-reconcile" data-task-id="${esc(task.task_id)}" data-call-id="${esc(c.call_id)}" data-tool-name="${esc(c.tool_name || "")}">记录实际结果</button>
                    </div>
                  `
                    )
                    .join("")}
                </div>
              </div>`
            : ""
        }

        <!-- Pending Approvals -->
        ${pendingApprovals
          .map(
            (a) => `
          <div class="cl-decision-card approval" data-dirty-scope="task-inputs">
            <div class="cl-decision-head">
              <strong>待处理审批 · ${esc(a.operation)}</strong>
              <span class="cl-hint">${a.approval_type === "task_plan" ? `计划 v${a.plan_version || 1}` : `批量操作 (${(a.calls || []).length})`}</span>
            </div>
            <div class="cl-decision-body">
              ${a.reason ? `<p><strong>原因：</strong>${esc(a.reason)}</p>` : ""}
              ${a.impact ? `<p><strong>影响：</strong>${esc(a.impact)}</p>` : ""}
              ${a.rollback ? `<p><strong>回滚：</strong>${esc(a.rollback)}</p>` : ""}
              ${a.message ? `<p style="white-space:pre-wrap;">${esc(a.message)}</p>` : ""}
              ${
                (a.calls || []).length
                  ? `<details class="cl-details" data-detail-key="apr-${esc(a.approval_id)}" style="margin:8px 0 0;">
                      <summary><span>展开调用参数 JSON (${a.calls.length} 项)</span></summary>
                      <div class="cl-details-body">
                        ${a.calls
                          .map(
                            (call, idx) => `
                          <div style="margin-bottom:8px;">
                            <div class="cl-hint"><strong>#${idx + 1} ${esc(call.tool_name || "tool")}</strong> ${call.signature ? `<code>${esc(call.signature)}</code>` : ""}</div>
                            <pre class="cl-json-pre">${esc(JSON.stringify(call.arguments ?? call, null, 2))}</pre>
                          </div>
                        `
                          )
                          .join("")}
                      </div>
                    </details>`
                  : ""
              }
              <div class="cl-decision-row">
                <input
                  type="text"
                  class="cl-input"
                  style="flex:1;min-width:200px;"
                  placeholder="可选审批备注或拒绝原因..."
                  data-approval-note="${esc(a.approval_id)}"
                />
                <button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-approve-id="${esc(a.approval_id)}" data-decision="approved" data-task-id="${esc(task.task_id)}">批准执行</button>
                <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-approve-id="${esc(a.approval_id)}" data-decision="rejected" data-task-id="${esc(task.task_id)}">拒绝</button>
              </div>
            </div>
          </div>
        `
          )
          .join("")}

        <!-- Pending Questions -->
        ${pendingQuestions
          .map(
            (q) => `
          <div class="cl-decision-card question" data-dirty-scope="task-inputs">
            <div class="cl-decision-head">
              <strong>待回答提问</strong>
              <span class="cl-hint">${esc(fmtTime(q.created_at))}</span>
            </div>
            <div class="cl-decision-body">
              <p style="font-weight:500;">${esc(q.question)}</p>
              ${q.recommendation ? `<p class="cl-hint">建议：${esc(q.recommendation)}</p>` : ""}
              ${
                (q.options || []).length
                  ? `<div class="cl-actions" style="margin:8px 0;">
                      ${q.options
                        .map(
                          (opt) =>
                            `<button type="button" class="cl-btn cl-btn-sm" data-quick-answer="${esc(opt)}" data-question-id="${esc(q.question_id)}" data-task-id="${esc(task.task_id)}">${esc(opt)}</button>`
                        )
                        .join("")}
                    </div>`
                  : ""
              }
              <div class="cl-decision-row">
                <input
                  type="text"
                  class="cl-input"
                  style="flex:1;min-width:200px;"
                  placeholder="输入回答..."
                  data-question-input="${esc(q.question_id)}"
                />
                <button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-submit-answer="${esc(q.question_id)}" data-task-id="${esc(task.task_id)}">提交回答</button>
              </div>
            </div>
          </div>
        `
          )
          .join("")}

        <!-- Execution Plan Steps -->
        <div class="cl-card" style="margin-bottom:14px;">
          <div class="cl-card-title">
            <span>执行计划清单</span>
            <span class="cl-hint">${doneSteps} / ${totalSteps}</span>
          </div>
          ${
            steps.length
              ? `<div class="cl-step-list">
                  ${steps
                    .map((s, idx) => {
                      const isCurrent = s.status === "running" || (task.current_step_id && s.id === task.current_step_id && s.status !== "completed");
                      const cls = s.status === "completed" ? "completed" : isCurrent ? "running" : s.status;
                      return `
                        <div class="cl-step-row ${esc(cls)}">
                          <span class="cl-step-idx">${s.status === "completed" ? "✓" : idx + 1}</span>
                          <div style="min-width:0;flex:1;">
                            <div style="display:flex;justify-content:space-between;gap:8px;">
                              <strong>${esc(s.title)}</strong>
                              <span class="cl-hint">${esc(s.status)}</span>
                            </div>
                            ${s.instruction ? `<div class="cl-hint" style="margin-top:2px;">${esc(s.instruction)}</div>` : ""}
                            ${s.summary ? `<div class="cl-hint" style="margin-top:2px;color:var(--green);">${esc(s.summary)}</div>` : ""}
                          </div>
                        </div>
                      `;
                    })
                    .join("")}
                </div>`
              : `<div class="cl-hint">暂未提交步骤，后台正进行只读规划。</div>`
          }
        </div>

        <!-- Token & Context Watermark -->
        <div class="cl-card" style="margin-bottom:14px;">
          <div class="cl-card-title">
            <span>Token 与上下文水位</span>
            <span class="cl-hint">${esc(fmtNum(estCtx))} / ${esc(fmtNum(handoffThreshold))} tokens (${ctxRatioPct}%)</span>
          </div>
          <div class="cl-progress-track">
            <div class="cl-progress-fill ${ctxRatioPct >= 85 ? "danger" : ctxRatioPct >= 60 ? "" : "green"}" style="width:${ctxRatioPct}%"></div>
          </div>
          <details class="cl-details" data-detail-key="usage-${esc(task.task_id)}" style="margin-top:12px;margin-bottom:0;">
            <summary>
              <span>展开详细消耗指标</span>
              <span class="cl-hint">累计 ${esc(fmtNum(usage.total_tokens || 0))} tokens</span>
            </summary>
            <div class="cl-details-body">
              <div class="cl-stat-grid">
                <div class="cl-stat-box"><span>累计 Token</span><strong>${esc(fmtNum(usage.total_tokens || 0))}</strong></div>
                <div class="cl-stat-box"><span>估算上下文</span><strong>${esc(fmtNum(estCtx))}</strong></div>
                <div class="cl-stat-box"><span>压缩阈值 (${handoffPct}%)</span><strong>${esc(fmtNum(handoffThreshold))}</strong></div>
                <div class="cl-stat-box"><span>已交接次数</span><strong>${usage.handoff_count || 0}</strong></div>
                <div class="cl-stat-box"><span>工具调用次数</span><strong>${usage.tool_calls || 0}${budget.max_total_tool_calls ? ` / ${budget.max_total_tool_calls}` : ""}</strong></div>
                <div class="cl-stat-box"><span>运行轮次</span><strong>${usage.ticks_used || 0}${budget.max_total_ticks ? ` / ${budget.max_total_ticks}` : ""}</strong></div>
              </div>
            </div>
          </details>
        </div>

        <!-- Steer -->
        <div class="cl-card" style="margin-bottom:14px;" data-dirty-scope="task-inputs">
          <div class="cl-card-title">
            <span>途中引导 (Steer)</span>
            <span class="cl-hint">修订 #${task.input_revision || 0}</span>
          </div>
          ${
            (task.guidance || []).length
              ? `<div style="max-height:120px;overflow:auto;margin-bottom:10px;">
                  ${task.guidance
                    .slice(-5)
                    .map(
                      (g) =>
                        `<div class="cl-hint" style="padding:5px 8px;background:var(--panel-2);border-radius:5px;margin-bottom:4px;"><span>${esc(fmtTime(g.time))}</span> · <span style="color:var(--ink);">${esc(g.text)}</span></div>`
                    )
                    .join("")}
                </div>`
              : ""
          }
          ${
            !isTerminal
              ? `<div style="display:flex;gap:8px;align-items:center;">
                  <input id="task-steer-input" type="text" class="cl-input" style="flex:1;min-width:0;" placeholder="输入途中补充指令，将在下一轮醒来生效..." />
                  <button type="button" class="cl-btn cl-btn-primary" data-action="send-steer" data-task-id="${esc(task.task_id)}">发送引导</button>
                </div>`
              : `<div class="cl-hint">任务已结束，无法继续发送引导。</div>`
          }
        </div>

        <!-- Task Files & Cleanup -->
        <details class="cl-details" data-detail-key="files-${esc(task.task_id)}">
          <summary>
            <span>持久化文件与清理</span>
            <span class="cl-hint">${files.length} 个文件</span>
          </summary>
          <div class="cl-details-body">
            <div class="cl-actions" style="margin-bottom:10px;">
              <button type="button" class="cl-btn cl-btn-sm" data-cleanup-scope="task_cache" data-task-id="${esc(task.task_id)}">清理缓存</button>
              ${task.status !== "running" ? `<button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-cleanup-scope="task_history" data-task-id="${esc(task.task_id)}">删除历史</button>` : ""}
            </div>
            ${
              files.length
                ? files
                    .map(
                      (f) => `
                  <div class="cl-file-row">
                    <code>${esc(f.rel_path)}</code>
                    <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;">
                      <span class="cl-hint">${esc(fmtBytes(f.bytes))}</span>
                      <button type="button" class="cl-btn cl-btn-sm" data-action="read-record" data-rel-path="${esc(f.rel_path)}" data-task-id="${esc(task.task_id)}">只读预览</button>
                    </div>
                  </div>
                `
                    )
                    .join("")
                : `<div class="cl-hint">暂无持久化记录文件。</div>`
            }
          </div>
        </details>

        <!-- Messages Timeline -->
        <details class="cl-details" data-detail-key="msg-${esc(task.task_id)}">
          <summary>
            <span>任务消息时间线</span>
            <span class="cl-hint">${messages.length} 条</span>
          </summary>
          <div class="cl-details-body task-message-scroll" data-scroll-key="msg-scroll-${esc(task.task_id)}">
            ${
              messages.length
                ? messages
                    .slice()
                    .reverse()
                    .map(
                      (m) => `
                  <div class="cl-msg-item">
                    <div class="cl-msg-meta">${esc(fmtTime(m.time))} · ${esc(m.msg_kind || "status")} · ${esc(m.delivery || "recorded")}</div>
                    <p class="cl-msg-text">${esc(m.text || "")}</p>
                  </div>
                `
                    )
                    .join("")
                : `<div class="cl-hint">暂无消息记录。</div>`
            }
          </div>
        </details>

        <!-- Tool Call Audit Journal -->
        <details class="cl-details" data-detail-key="journal-${esc(task.task_id)}" style="margin-bottom:${resolvedApprovals.length || answeredQuestions.length ? "12px" : "0"};">
          <summary>
            <span>工具调用审计日志</span>
            <span class="cl-hint">${journal.length} 次</span>
          </summary>
          <div class="cl-details-body task-message-scroll" data-scroll-key="journal-scroll-${esc(task.task_id)}">
            ${
              journal.length
                ? journal
                    .slice()
                    .reverse()
                    .map(
                      (j) => `
                  <div class="cl-file-row">
                    <div>
                      <code>${esc(j.tool_name || j.tool || "tool")}</code>
                      <span class="cl-hint" style="margin-left:6px;">${esc(j.status || "-")} · ${esc(fmtTime(j.time))}</span>
                    </div>
                    <span class="cl-hint">${j.duration_ms ? `${j.duration_ms}ms` : ""}</span>
                  </div>
                `
                    )
                    .join("")
                : `<div class="cl-hint">暂无工具调用记录。</div>`
            }
          </div>
        </details>

        ${
          resolvedApprovals.length || answeredQuestions.length
            ? `<details class="cl-details" data-detail-key="hist-${esc(task.task_id)}" style="margin-bottom:0;">
                <summary>
                  <span>已处理审批与提问历史</span>
                  <span class="cl-hint">${resolvedApprovals.length + answeredQuestions.length} 条</span>
                </summary>
                <div class="cl-details-body">
                  ${resolvedApprovals
                    .map(
                      (a) =>
                        `<div class="cl-file-row"><span>[审批] ${esc(a.operation)}</span><span class="cl-hint">${esc(a.decision || a.status)} ${esc(a.decision_note || "")}</span></div>`
                    )
                    .join("")}
                  ${answeredQuestions
                    .map(
                      (q) =>
                        `<div class="cl-file-row"><span>[提问] ${esc(q.question)}</span><span class="cl-hint">${esc(q.answer || q.status)}</span></div>`
                    )
                    .join("")}
                </div>
              </details>`
            : ""
        }
      </div>
    `;
  }

  function renderProjectSummaryTab(project) {
    const st = (store.state.storage?.projects || []).find((x) => x.project_id === project.project_id) || {
      bytes: 0,
      cache_bytes: 0,
      tasks: store.getTasksForProject(project.project_id).length,
    };
    const sharing = project.sharing || {};

    return `
      <div class="cl-grid-2">
        <div class="cl-card" data-dirty-scope="summary">
          <div class="cl-card-title">
            <span>项目摘要 (SUMMARY.md)</span>
            <div class="cl-actions">
              <button type="button" class="cl-btn cl-btn-sm" data-action="draft-project-summary" data-project-id="${esc(project.project_id)}">自动草拟</button>
              <button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-action="save-project-summary" data-project-id="${esc(project.project_id)}">保存摘要</button>
            </div>
          </div>
          <p class="cl-hint" style="margin:0 0 10px;">用于跨任务上下文交接，保存前自动执行敏感信息脱敏。</p>
          <textarea id="proj-summary-editor" class="cl-textarea" rows="12" placeholder="记录项目目标、结构约定与最新进展...">${esc(project.summary || "")}</textarea>
          <div class="cl-hint" style="margin-top:8px;">
            来源：${esc(project.summary_kind || "未记录")} ${project.summary_source_task_id ? `· ${esc(project.summary_source_task_id)}` : ""}
          </div>
        </div>

        <div>
          <div class="cl-card" data-dirty-scope="summary">
            <div class="cl-card-title"><span>摘要共享策略</span></div>
            <div class="cl-field">
              <label class="cl-check-card">
                <input id="share-with-daily" type="checkbox" ${sharing.share_with_daily ? "checked" : ""} />
                <span>
                  <strong>共享给日常对话</strong>
                  <div class="cl-hint">在关联会话的日常对话中附带简短项目摘要。</div>
                </span>
              </label>
            </div>
            <div class="cl-field">
              <label for="daily-summary-chars">日常共享字符上限</label>
              <input id="daily-summary-chars" type="number" class="cl-input" min="100" max="4000" value="${Number(sharing.daily_summary_chars || 600)}" />
            </div>
            <div class="cl-field">
              <label class="cl-check-card">
                <input id="share-with-tasks" type="checkbox" ${sharing.share_with_tasks !== false ? "checked" : ""} />
                <span>
                  <strong>共享给同项目新任务</strong>
                  <div class="cl-hint">新建任务时注入本项目摘要。</div>
                </span>
              </label>
            </div>
            <div class="cl-field">
              <label for="task-summary-chars">任务共享字符上限</label>
              <input id="task-summary-chars" type="number" class="cl-input" min="200" max="12000" value="${Number(sharing.task_summary_chars || 3000)}" />
            </div>
            <button type="button" class="cl-btn cl-btn-primary" data-action="save-sharing" data-project-id="${esc(project.project_id)}">保存共享设置</button>
          </div>

          <div class="cl-card">
            <div class="cl-card-title"><span>项目存储与安全清理</span></div>
            <div class="cl-stat-grid" style="margin-bottom:14px;">
              <div class="cl-stat-box"><span>任务数</span><strong>${st.tasks}</strong></div>
              <div class="cl-stat-box"><span>总占用</span><strong>${esc(fmtBytes(st.bytes))}</strong></div>
              <div class="cl-stat-box"><span>缓存占用</span><strong>${esc(fmtBytes(st.cache_bytes))}</strong></div>
            </div>
            <div class="cl-actions">
              <button type="button" class="cl-btn" data-cleanup-scope="project_cache" data-project-id="${esc(project.project_id)}">清理项目缓存</button>
              <button type="button" class="cl-btn cl-btn-danger" data-cleanup-scope="project" data-project-id="${esc(project.project_id)}">删除整个项目</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderProfileSummaryBoxHtml(profileId) {
    const prof = store.getProfile(profileId) || store.state.profiles[0];
    if (!prof) {
      return `<span>未找到所选方案配置。</span>`;
    }
    const c = prof.continuity || {};
    const b = prof.budget || {};
    const ctxTok = Number(c.context_tokens || 100000);
    const ctxPct = Number(c.context_percent || 55);
    const threshold = Math.round((ctxTok * ctxPct) / 100);
    const tokLimit = Number(b.max_total_tokens || 0) > 0 ? fmtNum(b.max_total_tokens) : "不限";
    return `
      <div>
        <strong>${esc(modeLabel(prof.permission_mode))}</strong>
        <span style="margin-left:8px;">交接阈值 ${esc(fmtNum(threshold))} (${ctxPct}% / ${esc(fmtNum(ctxTok))})</span>
        <span style="margin-left:8px;">轮次上限 ${Number(b.max_total_ticks || 40)} · 时长 ${Number(b.max_total_seconds || 1800)}s · Token 上限 ${esc(tokLimit)}</span>
      </div>
      <button type="button" class="cl-btn cl-btn-sm" data-action="jump-edit-profile" data-profile-id="${esc(prof.profile_id)}">编辑该方案 →</button>
    `;
  }

  function renderProjectSettingsTab(project) {
    const es = project.execution_settings || {};
    const profiles = store.state.profiles || [];
    const secrets = (store.state.credentials || []).filter((c) => c.kind !== "personal");
    const authCreds = new Set(es.authorized_credentials || []);

    return `
      <form id="proj-settings-form" class="cl-card" data-dirty-scope="project-settings" data-project-id="${esc(project.project_id)}">
        <div class="cl-card-title">
          <span>项目设置与工作区边界</span>
          <button type="submit" class="cl-btn cl-btn-primary">保存项目设置</button>
        </div>

        <div class="cl-grid-2">
          <div class="cl-field">
            <label for="ps-title">项目名称</label>
            <input id="ps-title" type="text" class="cl-input" value="${esc(project.title)}" required />
          </div>
          <div class="cl-field">
            <label for="ps-category">项目分类</label>
            <input id="ps-category" type="text" class="cl-input" value="${esc(project.category || "通用")}" />
          </div>
        </div>

        <div class="cl-field">
          <label for="ps-profile">关联方案</label>
          <select id="ps-profile" class="cl-select" style="margin-bottom:8px;">
            ${profiles
              .map(
                (pr) =>
                  `<option value="${esc(pr.profile_id)}" ${pr.profile_id === project.profile_id ? "selected" : ""}>${esc(pr.name)}${pr.is_default ? " (默认)" : ""}</option>`
              )
              .join("")}
          </select>
          <div id="proj-profile-preview" class="cl-readonly-box">
            ${renderProfileSummaryBoxHtml(project.profile_id)}
          </div>
        </div>

        <div class="cl-grid-2">
          <div class="cl-field">
            <label for="ps-roots">授权工作目录 (每行一个路径)</label>
            <textarea id="ps-roots" class="cl-textarea mono" rows="4" placeholder="/workspace/my-project">${esc((es.roots || []).join("\n"))}</textarea>
          </div>
          <div class="cl-field">
            <label for="ps-warnings">本项目审批规则 (每行一条，例如 审批:*git push*)</label>
            <textarea id="ps-warnings" class="cl-textarea" rows="4" placeholder="审批:*git push*&#10;禁止直接修改生产配置">${esc((es.warnings || []).join("\n"))}</textarea>
          </div>
        </div>

        <div class="cl-field">
          <label for="ps-task-prompt">本项目补充任务指引</label>
          <textarea id="ps-task-prompt" class="cl-textarea" rows="3" placeholder="例如：修改代码后必须运行 pytest 验证并汇报差异...">${esc(es.task_prompt || "")}</textarea>
        </div>

        <div class="cl-field">
          <label>本项目专属密钥授权（仅子进程环境变量注入，不进入模型上下文）</label>
          ${
            secrets.length
              ? `<div class="cl-check-grid">
                  ${secrets
                    .map(
                      (c) => `
                    <label class="cl-check-card">
                      <input type="checkbox" name="ps-creds" value="${esc(c.credential_id)}" ${authCreds.has(c.credential_id) ? "checked" : ""} />
                      <span>
                        <strong>${esc(c.label)}</strong>
                        <div class="cl-hint"><code>${esc(c.env_var || "(未设变量名)")}</code> · ${esc(c.scope === "project" ? "项目限定" : "全局")}</div>
                      </span>
                    </label>
                  `
                    )
                    .join("")}
                </div>`
              : `<div class="cl-hint">私人保险箱中暂无可用密钥，可前往「系统设置 → 私人保险箱」添加。</div>`
          }
        </div>
      </form>
    `;
  }

  // ── Route 2: Profiles (方案管理) ─────────────────────────────────────────

  function ensureProfileDraft() {
    if (!store.selectedProfileId) {
      profileDraft = null;
      profileDraftId = "";
      return null;
    }
    const prof = store.getProfile(store.selectedProfileId);
    if (!prof) {
      profileDraft = null;
      profileDraftId = "";
      return null;
    }
    if (profileDraftId !== prof.profile_id || !store.isDirty("profile")) {
      profileDraft = JSON.parse(JSON.stringify(prof));
      profileDraftId = prof.profile_id;
    }
    return profileDraft;
  }

  function syncDraftInputsFromDom() {
    if (!profileDraft || !viewEl?.querySelector("#profile-editor-form")) return;
    profileDraft.name = viewEl.querySelector("#prof-name")?.value.trim() || profileDraft.name;
    profileDraft.description = viewEl.querySelector("#prof-desc")?.value.trim() || "";
    profileDraft.permission_mode = viewEl.querySelector("#prof-mode")?.value || "standard";
    profileDraft.system_prompt = viewEl.querySelector("#prof-sys-prompt")?.value || "";
    profileDraft.task_prompt = viewEl.querySelector("#prof-task-prompt")?.value || "";
    profileDraft.authorized_credentials = [...viewEl.querySelectorAll('input[name="prof-creds"]:checked')].map(
      (el) => el.value
    );
    profileDraft.continuity = {
      context_tokens: Number(viewEl.querySelector("#prof-ctx-tok")?.value || 100000),
      context_percent: Number(viewEl.querySelector("#prof-ctx-pct")?.value || 55),
      summary_chars: Number(viewEl.querySelector("#prof-sum-chars")?.value || 5000),
      ingress_cap_bytes: Number(viewEl.querySelector("#prof-ingress")?.value || 14336),
    };
    profileDraft.budget = {
      native_steps: Number(viewEl.querySelector("#prof-native-steps")?.value || 24),
      max_total_tokens: Number(viewEl.querySelector("#prof-max-tok")?.value || 0),
      max_tokens_per_tick: Number(viewEl.querySelector("#prof-tick-tok")?.value || 0),
      max_total_tool_calls: Number(viewEl.querySelector("#prof-tool-calls")?.value || 0),
      max_total_ticks: Number(viewEl.querySelector("#prof-ticks")?.value || 40),
      max_total_seconds: Number(viewEl.querySelector("#prof-secs")?.value || 1800),
    };
  }

  function renderPluginCard(plugin, draft) {
    const plugId = plugin.name || "";
    const tools = plugin.tools || [];
    const blacklist = new Set(draft.plugin_blacklist || []);
    const disabledTools = new Set(draft.disabled_tools || []);
    const riskOverrides = draft.tool_risk_overrides || {};
    const hostEnabled = plugin.host_enabled !== false;
    const isProtected = Boolean(plugin.protected);
    const isPluginOn = isProtected || (hostEnabled && !blacklist.has(plugId));
    const enabledToolCount = isPluginOn
      ? tools.filter((t) => !disabledTools.has(t.name)).length
      : 0;

    let statusText = "";
    let statusClass = "";
    if (isProtected) {
      statusText = `核心受保护 · ${enabledToolCount}/${tools.length} 工具`;
      statusClass = "is-on";
    } else if (!hostEnabled) {
      statusText = "宿主已停用";
    } else if (isPluginOn) {
      statusText = `已接入 · ${enabledToolCount}/${tools.length} 工具`;
      statusClass = "is-on";
    } else {
      statusText = `已禁用 · 0/${tools.length} 工具`;
    }

    const avatarInner = plugin.logo_data_url
      ? `<img src="${esc(plugin.logo_data_url)}" alt="${esc(plugin.display_name || plugId)}" />`
      : PLUGIN_FALLBACK_SVG;

    return `
      <details class="plugin-card" data-detail-key="plug-${esc(plugId)}">
        <summary>
          <span class="plugin-avatar">${avatarInner}</span>
          <div class="plugin-meta">
            <div class="plugin-title-row">
              <strong>${esc(plugin.display_name || plugId)}</strong>
              <span class="plugin-status-meta ${statusClass}">${esc(statusText)}</span>
            </div>
            <p class="plugin-desc" title="${esc(plugin.description || "")}">${esc(plugin.description || "宿主扩展插件工具集")}</p>
          </div>
          <div class="plugin-card-right">
            <button
              type="button"
              class="cl-switch"
              role="switch"
              aria-checked="${isPluginOn ? "true" : "false"}"
              aria-label="切换插件 ${esc(plugin.display_name || plugId)}"
              data-toggle-plugin="${esc(plugId)}"
              ${isProtected || !hostEnabled ? "disabled" : ""}
            >
              <span class="cl-switch-thumb"></span>
            </button>
            <span class="plugin-chevron">${CHEVRON_SVG}</span>
          </div>
        </summary>
        <div class="plugin-tools-list">
          ${
            tools.length
              ? tools
                  .map((t) => {
                    const toolOn = isPluginOn && !disabledTools.has(t.name);
                    const effRisk = riskOverrides[t.name] || t.default_risk || "work";
                    const riskVal = effRisk === "high" ? "high" : "normal";
                    return `
                      <div class="plugin-tool-row">
                        <div class="plugin-tool-info">
                          <div class="plugin-tool-name-line">
                            <strong>${esc(t.display_name || t.name)}</strong>
                            <code>${esc(t.name)}</code>
                          </div>
                          ${t.description ? `<div class="plugin-tool-desc">${esc(t.description)}</div>` : ""}
                        </div>
                        <div class="plugin-tool-controls">
                          <select
                            class="risk-select"
                            data-tool-risk="${esc(t.name)}"
                            data-default-risk="${esc(t.default_risk || "work")}"
                            aria-label="风险级别"
                            ${!isPluginOn ? "disabled" : ""}
                          >
                            <option value="normal" ${riskVal === "normal" ? "selected" : ""}>常规</option>
                            <option value="high" ${riskVal === "high" ? "selected" : ""}>高危需审批</option>
                          </select>
                          <button
                            type="button"
                            class="cl-switch"
                            role="switch"
                            aria-checked="${toolOn ? "true" : "false"}"
                            aria-label="切换工具 ${esc(t.display_name || t.name)}"
                            data-toggle-tool="${esc(t.name)}"
                            ${!isPluginOn || isProtected ? "disabled" : ""}
                          >
                            <span class="cl-switch-thumb"></span>
                          </button>
                        </div>
                      </div>
                    `;
                  })
                  .join("")
              : `<div class="cl-hint" style="padding:8px 4px;">该插件未注册独立工具。</div>`
          }
        </div>
      </details>
    `;
  }

  function renderProfilesOverview() {
    const profiles = store.state.profiles || [];
    const q = (store.profileSearch || "").trim().toLowerCase();
    const filtered = profiles.filter((p) => {
      if (!q) return true;
      return (
        (p.name || "").toLowerCase().includes(q) ||
        (p.description || "").toLowerCase().includes(q) ||
        (p.profile_id || "").toLowerCase().includes(q)
      );
    });

    return `
      <div>
        <div class="cl-header">
          <div>
            <h1>方案管理</h1>
            <p class="cl-subtitle">按任务场景预设权限模式、插件工具能力、上下文连续性与预算上限。</p>
          </div>
          <div class="cl-actions">
            <button type="button" class="cl-btn cl-btn-primary" data-action="create-profile">+ 新建方案</button>
          </div>
        </div>

        ${
          profiles.length >= 2
            ? `<div class="project-toolbar">
                <input
                  id="prof-search-input"
                  type="search"
                  class="cl-input project-search-input"
                  placeholder="搜索方案名称或简介..."
                  value="${esc(store.profileSearch || "")}"
                />
              </div>`
            : ""
        }

        ${
          !filtered.length
            ? `<div class="cl-empty">
                <p>${profiles.length ? "未找到匹配的方案。" : "暂无方案，请新建一个方案。"}</p>
                ${!profiles.length ? `<button type="button" class="cl-btn cl-btn-primary" data-action="create-profile">+ 新建方案</button>` : ""}
              </div>`
            : `<div class="profile-list">
                ${filtered
                  .map((p) => {
                    const cont = p.continuity || {};
                    const bud = p.budget || {};
                    const ctxK = Number((Number(cont.context_tokens || 100000) / 1000).toFixed(1));
                    const ctxPct = Number(cont.context_percent || 55);
                    const maxTicks = Number(bud.max_total_ticks || 40);
                    const nativeSteps = Number(bud.native_steps || 24);
                    const disabledPlugins = (p.plugin_blacklist || []).length;
                    const disabledTools = (p.disabled_tools || []).length;
                    const descText = (p.description || "").trim() || "暂无方案简介。";

                    return `
                      <div class="profile-list-card" data-profile-card="${esc(p.profile_id)}">
                        <div
                          class="profile-list-main"
                          role="button"
                          tabindex="0"
                          data-select-profile="${esc(p.profile_id)}"
                          aria-label="进入配置 ${esc(p.name)}"
                        >
                          <span class="profile-list-icon">${profileModeIcon(p.permission_mode)}</span>
                          <div class="profile-list-body">
                            <div class="profile-list-title-row">
                              <span class="profile-list-title">${esc(p.name)}</span>
                              ${p.is_default ? `<span class="profile-tag is-default">默认</span>` : ""}
                              <span class="profile-tag">${esc(profileModeBadgeLabel(p.permission_mode))}</span>
                            </div>
                            <p class="profile-list-desc">${esc(descText)}</p>
                            <div class="profile-list-meta">
                              上下文 ${esc(ctxK)}K / ${esc(ctxPct)}% · 上限 ${esc(maxTicks)} 轮 · ${esc(nativeSteps)} 步/轮 · 已禁用 ${esc(disabledPlugins)} 插件 / ${esc(disabledTools)} 工具
                            </div>
                          </div>
                        </div>
                        <div class="profile-list-actions">
                          <button type="button" class="cl-btn cl-btn-sm cl-btn-primary" data-select-profile="${esc(p.profile_id)}">进入配置</button>
                          <button type="button" class="cl-btn cl-btn-sm" data-action="duplicate-profile" data-profile-id="${esc(p.profile_id)}">复制</button>
                          <button type="button" class="cl-btn cl-btn-sm" data-action="set-default-profile" data-profile-id="${esc(p.profile_id)}" ${p.is_default ? "disabled" : ""}>设为默认</button>
                          <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-action="delete-profile" data-profile-id="${esc(p.profile_id)}" ${p.profile_id === "default" ? "disabled" : ""}>删除</button>
                        </div>
                      </div>
                    `;
                  })
                  .join("")}
              </div>`
        }
      </div>
    `;
  }

  function renderProfileEditor(draft) {
    const plugins = store.state.plugins || [];
    const secrets = (store.state.credentials || []).filter((c) => c.kind !== "personal");

    let totalTools = 0;
    let enabledTools = 0;
    const bl = new Set(draft.plugin_blacklist || []);
    const dt = new Set(draft.disabled_tools || []);
    for (const pl of plugins) {
      const tools = pl.tools || [];
      totalTools += tools.length;
      const plOn = pl.protected || (pl.host_enabled !== false && !bl.has(pl.name));
      if (plOn) {
        enabledTools += tools.filter((t) => !dt.has(t.name)).length;
      }
    }

    return `
      <div>
        <div class="cl-header">
          <div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;">
              <button type="button" class="cl-btn cl-btn-sm" data-action="back-profiles">← 返回方案列表</button>
              ${draft.is_default ? `<span class="profile-tag is-default">默认</span>` : ""}
              <span class="profile-tag">${esc(profileModeBadgeLabel(draft.permission_mode))}</span>
            </div>
            <h1>${esc(draft.name)}</h1>
            <p class="cl-subtitle">${esc((draft.description || "").trim() || "按任务场景预设权限模式、插件工具能力、上下文连续性与预算上限。")}</p>
          </div>
          <div class="cl-actions">
            <button type="button" class="cl-btn cl-btn-sm" data-action="duplicate-profile" data-profile-id="${esc(draft.profile_id)}">复制</button>
            <button type="button" class="cl-btn cl-btn-sm" data-action="set-default-profile" data-profile-id="${esc(draft.profile_id)}" ${draft.is_default ? "disabled" : ""}>设为默认</button>
            <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-action="delete-profile" data-profile-id="${esc(draft.profile_id)}" ${draft.profile_id === "default" ? "disabled" : ""}>删除</button>
            <button type="submit" form="profile-editor-form" class="cl-btn cl-btn-sm cl-btn-primary">保存方案</button>
          </div>
        </div>

        <form id="profile-editor-form" data-dirty-scope="profile">
          <!-- 1. 基础与权限 -->
          <div class="cl-card">
            <div class="cl-card-title">
              <span>1. 基础与权限</span>
              <button type="submit" class="cl-btn cl-btn-sm cl-btn-primary">保存方案</button>
            </div>
            <div class="cl-grid-2">
              <div class="cl-field">
                <label for="prof-name">方案名称</label>
                <input id="prof-name" type="text" class="cl-input" value="${esc(draft.name)}" required />
              </div>
              <div class="cl-field">
                <label for="prof-mode">权限级别</label>
                <select id="prof-mode" class="cl-select">
                  <option value="readonly" ${draft.permission_mode === "readonly" ? "selected" : ""}>只读 readonly</option>
                  <option value="standard" ${draft.permission_mode === "standard" ? "selected" : ""}>标准 standard</option>
                  <option value="full" ${draft.permission_mode === "full" ? "selected" : ""}>全权限 full</option>
                </select>
              </div>
            </div>
            <div class="cl-field">
              <label for="prof-desc">方案简介</label>
              <input id="prof-desc" type="text" class="cl-input" value="${esc(draft.description || "")}" placeholder="描述此方案适用的工作类型与边界..." />
            </div>
          </div>

          <!-- 2. 插件与工具能力 -->
          <div class="cl-card">
            <div class="plugin-toolbar">
              <div>
                <strong style="font-size:13.5px;">2. 插件与工具能力</strong>
                <span class="cl-hint" style="margin-left:10px;">已接入 ${enabledTools} / ${totalTools} 工具</span>
              </div>
              <div class="cl-actions">
                <button type="button" class="cl-btn cl-btn-sm" data-action="disable-all-plugins">全部禁用</button>
                <button type="button" class="cl-btn cl-btn-sm" data-action="enable-all-plugins">全部启用</button>
              </div>
            </div>
            ${
              plugins.length
                ? `<div class="plugin-grid">${plugins.map((pl) => renderPluginCard(pl, draft)).join("")}</div>`
                : `<div class="cl-hint">当前未发现可用宿主插件工具组。</div>`
            }
          </div>

          <!-- 3. 上下文连续性与默认预算 -->
          <div class="cl-card">
            <div class="cl-card-title"><span>3. 上下文连续性与默认预算</span></div>
            <div class="cl-grid-auto" style="margin-bottom:14px;">
              <div class="cl-field"><label for="prof-ctx-tok">上下文窗口 (context_tokens)</label><input id="prof-ctx-tok" type="number" class="cl-input" value="${Number(draft.continuity?.context_tokens || 100000)}" /></div>
              <div class="cl-field"><label for="prof-ctx-pct">压缩阈值 % (context_percent)</label><input id="prof-ctx-pct" type="number" min="30" max="85" class="cl-input" value="${Number(draft.continuity?.context_percent || 55)}" /></div>
              <div class="cl-field"><label for="prof-sum-chars">交接摘要上限 (summary_chars)</label><input id="prof-sum-chars" type="number" class="cl-input" value="${Number(draft.continuity?.summary_chars || 5000)}" /></div>
              <div class="cl-field"><label for="prof-ingress">输出截断字节 (ingress_cap_bytes)</label><input id="prof-ingress" type="number" class="cl-input" value="${Number(draft.continuity?.ingress_cap_bytes || 14336)}" /></div>
            </div>
            <div class="cl-grid-auto">
              <div class="cl-field"><label for="prof-native-steps">单轮原生步数 (native_steps)</label><input id="prof-native-steps" type="number" class="cl-input" value="${Number(draft.budget?.native_steps || 24)}" /></div>
              <div class="cl-field"><label for="prof-max-tok">总 Token 上限 (0=不限)</label><input id="prof-max-tok" type="number" class="cl-input" value="${Number(draft.budget?.max_total_tokens || 0)}" /></div>
              <div class="cl-field"><label for="prof-tick-tok">单轮 Token 上限 (0=不限)</label><input id="prof-tick-tok" type="number" class="cl-input" value="${Number(draft.budget?.max_tokens_per_tick || 0)}" /></div>
              <div class="cl-field"><label for="prof-tool-calls">工具调用上限 (0=不限)</label><input id="prof-tool-calls" type="number" class="cl-input" value="${Number(draft.budget?.max_total_tool_calls || 0)}" /></div>
              <div class="cl-field"><label for="prof-ticks">最大轮次 (max_total_ticks)</label><input id="prof-ticks" type="number" class="cl-input" value="${Number(draft.budget?.max_total_ticks || 40)}" /></div>
              <div class="cl-field"><label for="prof-secs">最长秒数 (max_total_seconds)</label><input id="prof-secs" type="number" class="cl-input" value="${Number(draft.budget?.max_total_seconds || 1800)}" /></div>
            </div>
          </div>

          <!-- 4. 方案提示词与默认授权密钥 -->
          <div class="cl-card">
            <div class="cl-card-title"><span>4. 方案提示词与默认授权密钥</span></div>
            <div class="cl-grid-2">
              <div class="cl-field">
                <label for="prof-sys-prompt">系统提示词 (system_prompt)</label>
                <textarea id="prof-sys-prompt" class="cl-textarea" rows="3" placeholder="附加给任务执行器的系统级约定...">${esc(draft.system_prompt || "")}</textarea>
              </div>
              <div class="cl-field">
                <label for="prof-task-prompt">默认任务指引 (task_prompt)</label>
                <textarea id="prof-task-prompt" class="cl-textarea" rows="3" placeholder="附加到任务目标后的工程规范...">${esc(draft.task_prompt || "")}</textarea>
              </div>
            </div>
            <div class="cl-field">
              <label>默认授权密钥（仅子进程环境变量注入）</label>
              ${
                secrets.length
                  ? `<div class="cl-check-grid">
                      ${secrets
                        .map(
                          (c) => `
                        <label class="cl-check-card">
                          <input type="checkbox" name="prof-creds" value="${esc(c.credential_id)}" ${(draft.authorized_credentials || []).includes(c.credential_id) ? "checked" : ""} />
                          <span><strong>${esc(c.label)}</strong><div class="cl-hint"><code>${esc(c.env_var || "")}</code></div></span>
                        </label>
                      `
                        )
                        .join("")}
                    </div>`
                  : `<div class="cl-hint">暂无可用密钥，可前往「系统设置 → 私人保险箱」添加。</div>`
              }
            </div>
            <div style="display:flex;justify-content:flex-end;margin-top:12px;">
              <button type="submit" class="cl-btn cl-btn-primary">保存方案</button>
            </div>
          </div>
        </form>
      </div>
    `;
  }

  function renderProfiles() {
    if (!store.selectedProfileId) {
      return renderProfilesOverview();
    }
    const draft = ensureProfileDraft();
    if (!draft) {
      return renderProfilesOverview();
    }
    return renderProfileEditor(draft);
  }

  // ── Route 3: Settings (系统设置: identity | vault | storage) ─────────────

  function renderSettingsView() {
    const tab = store.settingsTab || "identity";
    return `
      <div>
        <div class="cl-header">
          <div>
            <h1>系统设置</h1>
            <p class="cl-subtitle">管理机器人身份通知、私人保险箱加密条目与连接存储清理。</p>
          </div>
        </div>

        <div class="cl-tabs" role="tablist">
          <button type="button" class="cl-tab ${tab === "identity" ? "active" : ""}" data-settings-tab="identity">机器人与通知</button>
          <button type="button" class="cl-tab ${tab === "vault" ? "active" : ""}" data-settings-tab="vault">私人保险箱</button>
          <button type="button" class="cl-tab ${tab === "storage" ? "active" : ""}" data-settings-tab="storage">连接与存储</button>
        </div>

        ${
          tab === "identity"
            ? renderSettingsIdentityTab()
            : tab === "vault"
              ? renderSettingsVaultTab()
              : renderSettingsStorageTab()
        }
      </div>
    `;
  }

  function renderSettingsIdentityTab() {
    const bots = store.getBots();
    const prefs = store.state.preferences || {};
    const defBot = prefs.default_bot || "";
    const progress = prefs.progress || {};

    if (!bots.length) {
      return `<div class="cl-empty"><p>当前未检测到机器人实例（在 AstrBot 宿主演示或接入平台后自动展示）。</p></div>`;
    }

    return `
      <div class="bot-card-grid" data-dirty-scope="settings">
        ${bots
          .map((b, idx) => {
            const botId = b.platform_id || b.umo || "";
            const isDef = (defBot && (b.platform_id === defBot || b.umo === defBot)) || (!defBot && idx === 0);
            const progCfg = (b.umo && progress[b.umo]) || (b.platform_id && progress[b.platform_id]) || progress || {};
            const progOn = progCfg.enabled !== false;
            const progInterval = Number(progCfg.min_interval_seconds ?? progCfg.interval_seconds ?? 30);

            return `
              <div class="bot-card" data-bot-card data-umo="${esc(b.umo || "")}" data-platform-id="${esc(b.platform_id || "")}">
                <div class="bot-card-head">
                  <span class="bot-avatar">${BOT_SVG}</span>
                  <div style="min-width:0;flex:1;">
                    <div style="font-size:14px;font-weight:600;color:var(--ink);">${esc(b.display_name || b.name || botId)}</div>
                    <div class="cl-hint" style="word-break:break-all;"><code>${esc(b.umo || b.platform_id)}</code></div>
                  </div>
                </div>
                <div class="bot-persona">
                  ${b.persona_name ? `<strong>${esc(b.persona_name)}</strong><div style="margin-top:2px;">${esc(b.persona_preview || "")}</div>` : esc(b.persona_preview || "暂未绑定特定 Persona 设定。")}
                </div>
                <div class="bot-notify-box">
                  <div class="bot-notify-row">
                    <span>任务进展私信通知</span>
                    <button
                      type="button"
                      class="cl-switch"
                      role="switch"
                      aria-checked="${progOn ? "true" : "false"}"
                      data-action="toggle-bot-progress"
                      data-umo="${esc(b.umo || "")}"
                      data-interval="${progInterval}"
                    >
                      <span class="cl-switch-thumb"></span>
                    </button>
                  </div>
                  <div class="bot-notify-row">
                    <span>最小推送间隔</span>
                    <select class="risk-select" data-bot-interval data-umo="${esc(b.umo || "")}" data-enabled="${progOn ? "1" : "0"}">
                      ${[0, 15, 30, 60, 120, 300]
                        .map(
                          (sec) =>
                            `<option value="${sec}" ${progInterval === sec ? "selected" : ""}>${sec === 0 ? "不限频 (0s)" : `${sec} 秒`}</option>`
                        )
                        .join("")}
                    </select>
                  </div>
                </div>
                <div class="bot-card-foot">
                  <span class="cl-hint">${isDef ? "当前默认身份" : esc(b.platform_name || b.platform_id)}</span>
                  <button
                    type="button"
                    class="cl-btn cl-btn-sm ${isDef ? "" : "cl-btn-primary"}"
                    data-action="set-default-bot"
                    data-bot-id="${esc(botId)}"
                    ${isDef ? "disabled" : ""}
                  >
                    ${isDef ? "已设为默认 Bot" : "设为默认 Bot"}
                  </button>
                </div>
              </div>
            `;
          })
          .join("")}
      </div>
    `;
  }

  function renderSettingsVaultTab() {
    const creds = store.state.credentials || [];
    const filter = store.vaultFilter || "all";
    const filtered = creds.filter((c) => {
      const k = c.kind === "personal" ? "personal" : "secret";
      return filter === "all" || filter === k;
    });

    return `
      <div>
        <div class="vault-explainer">
          采用 Fernet 对称加密本地存储。<strong>密钥与令牌</strong>仅在子进程执行工具时直接注入环境变量，不进入 LLM 上下文；<strong>个人私密资料</strong>用于安全保存个人邮箱、服务器别名、私有备注等信息，可按需选择是否允许任务引用。
        </div>

        <div class="vault-toolbar">
          <div class="vault-filters">
            <button type="button" class="vault-filter-pill ${filter === "all" ? "active" : ""}" data-vault-filter="all">全部 (${creds.length})</button>
            <button type="button" class="vault-filter-pill ${filter === "secret" ? "active" : ""}" data-vault-filter="secret">密钥与令牌 (${creds.filter((c) => c.kind !== "personal").length})</button>
            <button type="button" class="vault-filter-pill ${filter === "personal" ? "active" : ""}" data-vault-filter="personal">个人私密资料 (${creds.filter((c) => c.kind === "personal").length})</button>
          </div>
          <button type="button" class="cl-btn cl-btn-primary" data-action="open-cred-modal">+ 新增保险箱条目</button>
        </div>

        ${
          !filtered.length
            ? `<div class="cl-empty">
                <p>当前分类下暂无保险箱条目。</p>
                <button type="button" class="cl-btn cl-btn-primary" data-action="open-cred-modal">+ 新增保险箱条目</button>
              </div>`
            : `<div class="vault-list">
                ${filtered
                  .map((c) => {
                    const isPersonal = c.kind === "personal";
                    return `
                      <div class="vault-item-card">
                        <div class="vault-item-main">
                          <div class="vault-item-title">
                            <span class="vault-tag ${isPersonal ? "personal" : "secret"}">${isPersonal ? "个人资料" : "密钥"}</span>
                            <strong>${esc(c.label)}</strong>
                            ${!isPersonal && c.env_var ? `<code>${esc(c.env_var)}</code>` : ""}
                            ${isPersonal && c.share_with_tasks ? `<span class="vault-tag personal">任务可用</span>` : ""}
                          </div>
                          <div class="vault-item-meta">
                            <span>作用域：${c.scope === "project" ? `指定项目 (${(c.authorized_projects || []).length})` : "全局"}</span>
                            <span>密文：<code>${c.has_value ? esc(c.masked_value || "********") : "未设置"}</code></span>
                            ${c.note ? `<span>备注：${esc(c.note)}</span>` : ""}
                          </div>
                        </div>
                        <div class="vault-item-actions">
                          <button type="button" class="cl-btn cl-btn-sm" data-edit-cred="${esc(c.credential_id)}">编辑</button>
                          <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-delete-cred="${esc(c.credential_id)}">删除</button>
                        </div>
                      </div>
                    `;
                  })
                  .join("")}
              </div>`
        }
      </div>
    `;
  }

  function renderSettingsStorageTab() {
    const st = store.state.storage || { total_projects: 0, total_tasks: 0, total_bytes: 0, projects: [] };
    const rows = st.projects || [];
    const totalCache = rows.reduce((s, r) => s + Number(r.cache_bytes || 0), 0);

    return `
      <div>
        <div class="cl-card">
          <div class="cl-card-title"><span>连接认证</span></div>
          ${
            store.isStandalone()
              ? `<div class="cl-field" style="margin-bottom:0;">
                  <label for="set-standalone-token">独立 WebUI 访问令牌 (X-Agent-Lab-Token)</label>
                  <div style="display:flex;gap:8px;align-items:center;">
                    <input id="set-standalone-token" type="password" class="cl-input" style="flex:1;min-width:0;" value="${esc(store.getToken())}" placeholder="输入 standalone_webui_token" />
                    <button type="button" class="cl-btn cl-btn-primary" data-action="save-standalone-token">应用并重连</button>
                  </div>
                </div>`
              : `<p class="cl-hint" style="margin:0;">当前运行于 AstrBot 管理面板内嵌模式，连接认证由宿主管理会话自动接管。</p>`
          }
        </div>

        <div class="project-hero-strip">
          <div><strong>${st.total_projects || 0}</strong><span>项目数</span></div>
          <div><strong>${st.total_tasks || 0}</strong><span>任务记录</span></div>
          <div><strong>${esc(fmtBytes(st.total_bytes || 0))} (缓存 ${esc(fmtBytes(totalCache))})</strong><span>总磁盘占用</span></div>
        </div>

        <div class="cl-card" style="padding:0;overflow:hidden;">
          <table class="cl-table">
            <thead>
              <tr>
                <th>项目</th>
                <th>任务数</th>
                <th>缓存</th>
                <th>总占用</th>
                <th style="text-align:right;">清理</th>
              </tr>
            </thead>
            <tbody>
              ${
                rows.length
                  ? rows
                      .map(
                        (r) => `
                    <tr>
                      <td><button type="button" class="cl-link-btn" data-open-project="${esc(r.project_id)}">${esc(r.title)}</button></td>
                      <td>${r.tasks || 0}</td>
                      <td>${esc(fmtBytes(r.cache_bytes || 0))}</td>
                      <td>${esc(fmtBytes(r.bytes || 0))}</td>
                      <td style="text-align:right;white-space:nowrap;">
                        <button type="button" class="cl-btn cl-btn-sm" data-cleanup-scope="project_cache" data-project-id="${esc(r.project_id)}">清理缓存</button>
                        <button type="button" class="cl-btn cl-btn-sm cl-btn-danger" data-cleanup-scope="project" data-project-id="${esc(r.project_id)}">删除项目</button>
                      </td>
                    </tr>
                  `
                      )
                      .join("")
                  : `<tr><td colspan="5" class="cl-hint" style="text-align:center;padding:24px;">暂无项目存储记录</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // ── Main Render ──────────────────────────────────────────────────────────

  function render({ reason = "update" } = {}) {
    renderTopBar();
    renderSidebar();
    renderFeedback();
    if (reason === "chrome-only") return;

    const snap = captureViewState();
    if (viewEl) {
      if (store.route === "projects") {
        const proj = store.selectedProjectId ? store.getProject(store.selectedProjectId) : null;
        viewEl.innerHTML = proj ? renderProjectDetail(proj) : renderProjectsOverview();
      } else if (store.route === "profiles") {
        viewEl.innerHTML = renderProfiles();
      } else if (store.route === "settings") {
        viewEl.innerHTML = renderSettingsView();
      }
    }
    restoreViewState(snap);
    requestResize();
  }

  // ── Modals (Zero native dialogs) ─────────────────────────────────────────

  function openModal({ title, bodyHtml, footHtml = "", wide = false, onMount = null }) {
    closeModal();
    const wrap = document.createElement("div");
    wrap.className = "al-modal-backdrop";
    wrap.innerHTML = `
      <div class="al-modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
        <div class="al-modal-head">
          <h3>${esc(title)}</h3>
          <button type="button" class="al-modal-close" aria-label="关闭">×</button>
        </div>
        <div class="al-modal-body">${bodyHtml}</div>
        ${footHtml ? `<div class="al-modal-foot">${footHtml}</div>` : ""}
      </div>
    `;
    modalRoot.appendChild(wrap);
    store.setModalOpen(true);

    const close = () => {
      if (wrap.parentNode) {
        wrap.remove();
        store.setModalOpen(false);
      }
    };
    wrap.querySelector(".al-modal-close")?.addEventListener("click", close);
    wrap.addEventListener("click", (e) => {
      if (e.target === wrap) close();
    });
    if (typeof onMount === "function") onMount(wrap, close);
    requestResize();
    return { wrap, close };
  }

  function closeModal() {
    while (modalRoot && modalRoot.firstChild) {
      modalRoot.removeChild(modalRoot.firstChild);
      store.setModalOpen(false);
    }
  }

  function showConfirmModal({ title, message, confirmLabel = "确认", danger = true, onConfirm }) {
    openModal({
      title,
      bodyHtml: `<p style="margin:0;color:var(--muted);">${esc(message)}</p>`,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="button" class="cl-btn ${danger ? "cl-btn-danger" : "cl-btn-primary"}" id="m-confirm-ok">${esc(confirmLabel)}</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#m-confirm-ok")?.addEventListener("click", async () => {
          close();
          await onConfirm();
        });
      },
    });
  }

  function showInputModal({ title, label, placeholder = "", defaultValue = "", confirmLabel = "确认", danger = false, onSubmit }) {
    openModal({
      title,
      bodyHtml: `
        <form id="modal-input-form">
          <div class="cl-field">
            <label for="m-single-input">${esc(label)}</label>
            <input id="m-single-input" type="text" class="cl-input" value="${esc(defaultValue)}" placeholder="${esc(placeholder)}" />
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-input-form" class="cl-btn ${danger ? "cl-btn-danger" : "cl-btn-primary"}">${esc(confirmLabel)}</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-input-form")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const val = wrap.querySelector("#m-single-input").value.trim();
          close();
          await onSubmit(val);
        });
      },
    });
  }

  function showCreateProjectModal() {
    const profiles = store.state.profiles || [];
    const bots = store.getBots();
    openModal({
      title: "新建项目",
      bodyHtml: `
        <form id="modal-create-proj">
          <div class="cl-field">
            <label for="m-proj-title">项目名称</label>
            <input id="m-proj-title" type="text" class="cl-input" required placeholder="例如：订单中心重构" />
          </div>
          <div class="cl-grid-2">
            <div class="cl-field">
              <label for="m-proj-cat">项目分类</label>
              <input id="m-proj-cat" type="text" class="cl-input" value="通用" />
            </div>
            <div class="cl-field">
              <label for="m-proj-prof">关联方案</label>
              <select id="m-proj-prof" class="cl-select">
                ${profiles
                  .map(
                    (p) =>
                      `<option value="${esc(p.profile_id)}" ${p.is_default ? "selected" : ""}>${esc(p.name)}</option>`
                  )
                  .join("")}
              </select>
            </div>
          </div>
          ${
            bots.length
              ? `<div class="cl-field">
                  <label for="m-proj-bot">关联 Bot 实例</label>
                  <select id="m-proj-bot" class="cl-select">
                    ${bots
                      .map(
                        (b) =>
                          `<option value="${esc(b.umo || b.platform_id)}" data-platform="${esc(b.platform_id || "")}">${esc(b.display_name || b.name || b.platform_id)}</option>`
                      )
                      .join("")}
                  </select>
                </div>`
              : ""
          }
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-create-proj" class="cl-btn cl-btn-primary">创建项目</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-create-proj")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const botSel = wrap.querySelector("#m-proj-bot");
          const selectedOpt = botSel?.options?.[botSel.selectedIndex];
          try {
            await store.createProject({
              title: wrap.querySelector("#m-proj-title").value.trim(),
              category: wrap.querySelector("#m-proj-cat").value.trim() || "通用",
              profile_id: wrap.querySelector("#m-proj-prof")?.value || "",
              source_umo: botSel?.value || "",
              platform_id: selectedOpt?.getAttribute("data-platform") || "",
            });
            close();
            store.toast("项目已创建", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showCreateProfileModal() {
    openModal({
      title: "新建方案",
      bodyHtml: `
        <form id="modal-create-prof">
          <div class="cl-field">
            <label for="m-prof-name">方案名称 *</label>
            <input id="m-prof-name" type="text" class="cl-input" required placeholder="例如：测试验证方案" />
          </div>
          <div class="cl-field">
            <label for="m-prof-mode">权限级别</label>
            <select id="m-prof-mode" class="cl-select">
              <option value="readonly">只读 readonly</option>
              <option value="standard" selected>标准 standard</option>
              <option value="full">全权限 full</option>
            </select>
          </div>
          <div class="cl-field">
            <label for="m-prof-desc">简介</label>
            <input id="m-prof-desc" type="text" class="cl-input" placeholder="可选简介..." />
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-create-prof" class="cl-btn cl-btn-primary">创建方案</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-create-prof")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try {
            await store.saveProfile({
              name: wrap.querySelector("#m-prof-name").value.trim(),
              permission_mode: wrap.querySelector("#m-prof-mode").value,
              description: wrap.querySelector("#m-prof-desc").value.trim(),
            });
            profileDraftId = "";
            close();
            store.toast("方案已创建", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showCreateTaskModal(defaultProjectId = "") {
    const projects = store.state.projects || [];
    const profiles = store.state.profiles || [];
    const projId = defaultProjectId || store.selectedProjectId || projects[0]?.project_id || "";
    const curProj = store.getProject(projId);
    const defProfId = curProj?.profile_id || profiles.find((p) => p.is_default)?.profile_id || "";

    openModal({
      title: "新建隔离任务",
      bodyHtml: `
        <form id="modal-create-task">
          <div class="cl-field">
            <label for="m-task-goal">任务目标 *</label>
            <textarea id="m-task-goal" class="cl-textarea" rows="3" required placeholder="描述需要独立完成的目标与交付标准..."></textarea>
          </div>
          <div class="cl-grid-2">
            <div class="cl-field">
              <label for="m-task-proj">归属项目</label>
              <select id="m-task-proj" class="cl-select">
                <option value="">默认项目区</option>
                ${projects
                  .map(
                    (p) =>
                      `<option value="${esc(p.project_id)}" ${p.project_id === projId ? "selected" : ""}>${esc(p.title)}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="cl-field">
              <label for="m-task-prof">执行方案</label>
              <select id="m-task-prof" class="cl-select">
                ${profiles
                  .map(
                    (pr) =>
                      `<option value="${esc(pr.profile_id)}" ${pr.profile_id === defProfId ? "selected" : ""}>${esc(pr.name)} (${esc(pr.permission_mode)})</option>`
                  )
                  .join("")}
              </select>
            </div>
          </div>
          <div class="cl-field">
            <label for="m-task-constraints">约束条件（可选，每行一条）</label>
            <textarea id="m-task-constraints" class="cl-textarea" rows="2" placeholder="严禁修改生产数据库&#10;不安装额外系统依赖"></textarea>
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-create-task" class="cl-btn cl-btn-primary">启动任务</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-create-task")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const goal = wrap.querySelector("#m-task-goal").value.trim();
          const constraints = wrap
            .querySelector("#m-task-constraints")
            .value.split(/\r?\n/)
            .map((x) => x.trim())
            .filter(Boolean);
          try {
            await store.startTask({
              goal,
              project_id: wrap.querySelector("#m-task-proj").value,
              profile_id: wrap.querySelector("#m-task-prof").value,
              constraints,
            });
            close();
            store.toast("任务已启动", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showReconcileModal(taskId, callId, toolName) {
    openModal({
      title: `核对异常中断调用 · ${toolName || callId}`,
      bodyHtml: `
        <form id="modal-reconcile">
          <p class="cl-hint" style="margin-top:0;">call_id: <code>${esc(callId)}</code></p>
          <div class="cl-field">
            <label for="m-rec-status">记录实际执行结果</label>
            <select id="m-rec-status" class="cl-select">
              <option value="completed">completed — 已实际执行完成</option>
              <option value="failed">failed — 执行失败或未生效</option>
              <option value="not_started">not_started — 未执行，可重新执行</option>
            </select>
          </div>
          <div class="cl-field">
            <label for="m-rec-note">核对说明</label>
            <input id="m-rec-note" type="text" class="cl-input" placeholder="例如：确认文件已落盘 / 需重试" />
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-reconcile" class="cl-btn cl-btn-primary">提交结果</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-reconcile")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try {
            await store.reconcile(
              taskId,
              callId,
              wrap.querySelector("#m-rec-status").value,
              wrap.querySelector("#m-rec-note").value.trim()
            );
            close();
            store.toast("已提交中断调用核对", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showBudgetModal(task) {
    const b = task.execution_settings?.budget || {};
    openModal({
      title: `调整任务预算 · ${task.task_id}`,
      bodyHtml: `
        <form id="modal-budget">
          <div class="cl-grid-2">
            <div class="cl-field"><label for="mb-native">单轮原生步数 (native_steps)</label><input id="mb-native" type="number" class="cl-input" value="${Number(b.native_steps || 24)}" /></div>
            <div class="cl-field"><label for="mb-max-tok">总 Token 上限 (0=不限)</label><input id="mb-max-tok" type="number" class="cl-input" value="${Number(b.max_total_tokens || 0)}" /></div>
            <div class="cl-field"><label for="mb-tick-tok">单轮 Token 上限 (0=不限)</label><input id="mb-tick-tok" type="number" class="cl-input" value="${Number(b.max_tokens_per_tick || 0)}" /></div>
            <div class="cl-field"><label for="mb-tools">工具调用上限 (0=不限)</label><input id="mb-tools" type="number" class="cl-input" value="${Number(b.max_total_tool_calls || 0)}" /></div>
            <div class="cl-field"><label for="mb-ticks">最大轮次 (ticks)</label><input id="mb-ticks" type="number" class="cl-input" value="${Number(b.max_total_ticks || 40)}" /></div>
            <div class="cl-field"><label for="mb-secs">最长秒数</label><input id="mb-secs" type="number" class="cl-input" value="${Number(b.max_total_seconds || 1800)}" /></div>
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-budget" class="cl-btn cl-btn-primary">保存预算</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-budget")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try {
            await store.updateBudget(task.task_id, {
              native_steps: Number(wrap.querySelector("#mb-native").value || 24),
              max_total_tokens: Number(wrap.querySelector("#mb-max-tok").value || 0),
              max_tokens_per_tick: Number(wrap.querySelector("#mb-tick-tok").value || 0),
              max_total_tool_calls: Number(wrap.querySelector("#mb-tools").value || 0),
              max_total_ticks: Number(wrap.querySelector("#mb-ticks").value || 40),
              max_total_seconds: Number(wrap.querySelector("#mb-secs").value || 1800),
            });
            close();
            store.toast("任务预算已更新", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showMoveTaskModal(task) {
    const projects = store.state.projects || [];
    openModal({
      title: `归入项目 · ${task.task_id}`,
      bodyHtml: `
        <form id="modal-move-task">
          <div class="cl-field">
            <label for="m-move-proj">目标项目</label>
            <select id="m-move-proj" class="cl-select">
              ${projects
                .map(
                  (p) =>
                    `<option value="${esc(p.project_id)}" ${p.project_id === task.project_id ? "selected" : ""}>${esc(p.title)}</option>`
                )
                .join("")}
            </select>
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-move-task" class="cl-btn cl-btn-primary">确认归入</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-move-task")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try {
            await store.moveTask(task.task_id, wrap.querySelector("#m-move-proj").value);
            close();
            store.toast("任务已归入目标项目", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  async function showReadRecordModal(relPath, taskId) {
    try {
      const data = await store.readRecord(relPath, taskId);
      openModal({
        title: `只读预览 · ${data.rel_path || relPath}`,
        wide: true,
        bodyHtml: `
          <div class="cl-hint" style="margin-bottom:8px;">
            大小：${esc(fmtBytes(data.bytes || 0))} · ${data.truncated ? "内容已截断（仅展示头部）" : "完整内容（已自动脱敏）"}
          </div>
          <pre class="cl-json-pre" style="max-height:60dvh;">${esc(data.content || "")}</pre>
        `,
        footHtml: `<button type="button" class="cl-btn cl-btn-primary" data-m-cancel>关闭</button>`,
        onMount(wrap, close) {
          wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        },
      });
    } catch (err) {
      store.toast(err.message, "error");
    }
  }

  async function showCleanupModal(scope, { project_id = "", task_id = "" }) {
    try {
      const preview = await store.cleanupPreview(scope, { project_id, task_id });
      const paths = preview.paths || [];
      openModal({
        title: "双步安全清理确认",
        bodyHtml: `
          <div class="cl-decision-card unknown" style="margin-bottom:10px;">
            <strong>请确认待清理的物理路径</strong>
            <div class="cl-hint" style="margin-top:4px;">范围：<code>${esc(preview.scope || scope)}</code> · 预计释放：<strong>${esc(fmtBytes(preview.bytes || 0))}</strong> (${preview.path_count || paths.length} 项)</div>
          </div>
          ${
            paths.length
              ? `<pre class="cl-json-pre">${esc(paths.join("\n"))}</pre>`
              : `<p class="cl-hint">没有可清理的目录或文件。</p>`
          }
        `,
        footHtml: `
          <button type="button" class="cl-btn" data-m-cancel>取消</button>
          <button type="button" class="cl-btn cl-btn-danger" id="m-cleanup-confirm">确认清理</button>
        `,
        onMount(wrap, close) {
          wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
          wrap.querySelector("#m-cleanup-confirm")?.addEventListener("click", async () => {
            try {
              const res = await store.cleanupConfirm(preview.token);
              close();
              store.toast(`清理完成，释放 ${fmtBytes(res.removed_bytes || 0)}`, "success");
            } catch (err) {
              store.toast(err.message, "error");
            }
          });
        },
      });
    } catch (err) {
      store.toast(err.message, "error");
    }
  }

  function showCredentialModal(existing = null) {
    const isEdit = Boolean(existing);
    const projects = store.state.projects || [];
    const authProjs = new Set(existing?.authorized_projects || []);
    const initKind = existing?.kind === "personal" ? "personal" : "secret";

    openModal({
      title: isEdit ? `编辑条目 · ${existing.label}` : "新增保险箱条目",
      bodyHtml: `
        <form id="modal-cred-form">
          <div class="cl-grid-2">
            <div class="cl-field">
              <label for="mc-kind">条目类型</label>
              <select id="mc-kind" class="cl-select">
                <option value="secret" ${initKind === "secret" ? "selected" : ""}>密钥与令牌 (secret)</option>
                <option value="personal" ${initKind === "personal" ? "selected" : ""}>个人私密资料 (personal)</option>
              </select>
            </div>
            <div class="cl-field">
              <label for="mc-label">名称 *</label>
              <input id="mc-label" type="text" class="cl-input" required value="${esc(existing?.label || "")}" placeholder="例如：GitHub PAT / Git 个人邮箱" />
            </div>
          </div>

          <div id="mc-secret-fields" style="${initKind === "secret" ? "" : "display:none;"}">
            <div class="cl-grid-2">
              <div class="cl-field">
                <label for="mc-env">注入环境变量名 (env_var) *</label>
                <input id="mc-env" type="text" class="cl-input mono" value="${esc(existing?.env_var || "")}" placeholder="例如：GITHUB_TOKEN" />
              </div>
              <div class="cl-field">
                <label for="mc-provider">提供方</label>
                <select id="mc-provider" class="cl-select">
                  ${Object.entries(PROVIDER_LABELS)
                    .map(
                      ([k, lbl]) =>
                        `<option value="${esc(k)}" ${(existing?.provider || "generic") === k ? "selected" : ""}>${esc(lbl)}</option>`
                    )
                    .join("")}
                </select>
              </div>
            </div>
          </div>

          <div id="mc-personal-fields" style="${initKind === "personal" ? "" : "display:none;"}">
            <div class="cl-field">
              <label class="cl-check-card">
                <input id="mc-share-tasks" type="checkbox" ${existing?.share_with_tasks ? "checked" : ""} />
                <span>
                  <strong>允许任务按需引用 (share_with_tasks)</strong>
                  <div class="cl-hint">开启后，授权项目中的隔离任务可读取此个人资料（如 Git 提交邮箱或服务器别名）。</div>
                </span>
              </label>
            </div>
          </div>

          <div class="cl-field">
            <label for="mc-scope">作用范围</label>
            <select id="mc-scope" class="cl-select">
              <option value="global" ${(existing?.scope || "global") === "global" ? "selected" : ""}>global — 全局项目可用</option>
              <option value="project" ${existing?.scope === "project" ? "selected" : ""}>project — 仅限指定项目</option>
            </select>
          </div>

          <div class="cl-field" id="mc-proj-box" style="${existing?.scope === "project" ? "" : "display:none;"}">
            <label>授权项目</label>
            <div class="cl-check-grid">
              ${projects
                .map(
                  (p) =>
                    `<label class="cl-check-card"><input type="checkbox" name="mc-projs" value="${esc(p.project_id)}" ${authProjs.has(p.project_id) ? "checked" : ""} /><span>${esc(p.title)}</span></label>`
                )
                .join("")}
            </div>
          </div>

          <div class="cl-field">
            <label for="mc-secret">加密内容（只写不回显）${isEdit ? "" : " *"}</label>
            <input
              id="mc-secret"
              type="password"
              class="cl-input mono"
              ${isEdit ? "" : "required"}
              autocomplete="new-password"
              placeholder="${isEdit ? "留空则保持原有加密内容不变" : "输入密钥或私密内容，保存后仅显示 ********"}"
            />
          </div>

          <div class="cl-field">
            <label for="mc-note">备注说明</label>
            <input id="mc-note" type="text" class="cl-input" value="${esc(existing?.note || "")}" placeholder="用途、作用域或过期提示" />
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-cred-form" class="cl-btn cl-btn-primary">加密保存</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        const kindSel = wrap.querySelector("#mc-kind");
        const secBox = wrap.querySelector("#mc-secret-fields");
        const perBox = wrap.querySelector("#mc-personal-fields");
        const scopeSel = wrap.querySelector("#mc-scope");
        const projBox = wrap.querySelector("#mc-proj-box");

        kindSel?.addEventListener("change", () => {
          const isPers = kindSel.value === "personal";
          if (secBox) secBox.style.display = isPers ? "none" : "";
          if (perBox) perBox.style.display = isPers ? "" : "none";
        });
        scopeSel?.addEventListener("change", () => {
          if (projBox) projBox.style.display = scopeSel.value === "project" ? "" : "none";
        });

        wrap.querySelector("#modal-cred-form")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          const kind = kindSel.value === "personal" ? "personal" : "secret";
          const envVar = wrap.querySelector("#mc-env").value.trim();
          if (kind === "secret" && !envVar) {
            store.toast("密钥条目必须填写环境变量名 (env_var)", "error");
            return;
          }
          const payload = {
            kind,
            label: wrap.querySelector("#mc-label").value.trim(),
            provider: kind === "personal" ? "personal" : wrap.querySelector("#mc-provider").value,
            env_var: kind === "secret" ? envVar : "",
            inject_mode: kind === "secret" ? "env" : "reference",
            share_with_tasks: kind === "personal" ? Boolean(wrap.querySelector("#mc-share-tasks").checked) : false,
            scope: scopeSel.value,
            authorized_projects: [...wrap.querySelectorAll('input[name="mc-projs"]:checked')].map((el) => el.value),
            note: wrap.querySelector("#mc-note").value.trim(),
          };
          if (existing?.credential_id) payload.credential_id = existing.credential_id;
          const secretVal = wrap.querySelector("#mc-secret").value;
          if (secretVal) payload.value = secretVal;
          try {
            await store.saveCredential(payload);
            close();
            store.toast("保险箱条目已加密保存", "success");
          } catch (err) {
            store.toast(err.message, "error");
          }
        });
      },
    });
  }

  function showTokenModal() {
    openModal({
      title: "独立 WebUI 访问验证",
      bodyHtml: `
        <form id="modal-token-form">
          <div class="cl-field">
            <label for="mt-val">X-Agent-Lab-Token</label>
            <input id="mt-val" type="password" class="cl-input" required value="${esc(store.getToken())}" placeholder="请输入 standalone_webui_token" />
          </div>
        </form>
      `,
      footHtml: `
        <button type="button" class="cl-btn" data-m-cancel>取消</button>
        <button type="submit" form="modal-token-form" class="cl-btn cl-btn-primary">保存并重连</button>
      `,
      onMount(wrap, close) {
        wrap.querySelector("[data-m-cancel]")?.addEventListener("click", close);
        wrap.querySelector("#modal-token-form")?.addEventListener("submit", async (ev) => {
          ev.preventDefault();
          close();
          await store.setTokenAndReconnect(wrap.querySelector("#mt-val").value);
        });
      },
    });
  }

  // ── Form Collectors ──────────────────────────────────────────────────────

  function collectProfileForm() {
    if (!profileDraft) return null;
    syncDraftInputsFromDom();
    return {
      ...profileDraft,
      plugin_blacklist: [...new Set(profileDraft.plugin_blacklist || [])],
      disabled_tools: [...new Set(profileDraft.disabled_tools || [])],
      enabled_tools: [...new Set(profileDraft.enabled_tools || [])],
      tool_risk_overrides: { ...(profileDraft.tool_risk_overrides || {}) },
      authorized_credentials: [...new Set(profileDraft.authorized_credentials || [])],
    };
  }

  // ── Event Wiring (Single AbortController, Zero Duplicates) ───────────────

  function closeMobileRail() {
    shellEl?.classList.remove("rail-open");
    if (mobileBackdrop) mobileBackdrop.hidden = true;
  }

  document.addEventListener(
    "click",
    (ev) => {
      if (botPopover && !botPopover.hidden) {
        const wrap = ev.target.closest(".status-agent-wrap");
        if (!wrap) {
          botPopover.hidden = true;
          agentSwitcherBtn?.setAttribute("aria-expanded", "false");
        }
      }
    },
    { signal }
  );

  document.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key === "Escape") {
        if (modalRoot?.children.length) closeModal();
        if (botPopover && !botPopover.hidden) {
          botPopover.hidden = true;
          agentSwitcherBtn?.setAttribute("aria-expanded", "false");
        }
        closeMobileRail();
      }
    },
    { signal }
  );

  mobileBackdrop?.addEventListener("click", closeMobileRail, { signal });

  statusBarEl?.addEventListener(
    "click",
    async (ev) => {
      const mobileToggle = ev.target.closest("#mobile-nav-toggle");
      if (mobileToggle) {
        const open = shellEl?.classList.toggle("rail-open");
        if (mobileBackdrop) mobileBackdrop.hidden = !open;
        return;
      }

      if (ev.target.closest("#agent-switcher-btn")) {
        if (botPopover) {
          botPopover.hidden = !botPopover.hidden;
          agentSwitcherBtn?.setAttribute("aria-expanded", botPopover.hidden ? "false" : "true");
          if (!botPopover.hidden) renderBotPopover();
        }
        return;
      }

      const botItem = ev.target.closest("[data-select-bot]");
      if (botItem) {
        const botId = botItem.getAttribute("data-select-bot");
        if (botPopover) botPopover.hidden = true;
        agentSwitcherBtn?.setAttribute("aria-expanded", "false");
        try {
          await store.setDefaultBot(botId);
          store.toast("已切换默认 Bot 身份", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }

      const viewBtn = ev.target.closest("#status-view-btn");
      if (viewBtn?.dataset.taskId) {
        store.openTask(viewBtn.dataset.taskId);
        return;
      }

      if (ev.target.closest("#refresh-btn")) {
        store.refreshAll({ silent: false });
        return;
      }

      if (ev.target.closest("#settings-btn")) {
        store.clearDirty();
        store.navigate("settings", { settingsTab: "identity" });
      }
    },
    { signal }
  );

  railEl?.addEventListener(
    "click",
    (ev) => {
      const navBtn = ev.target.closest("[data-nav]");
      if (navBtn) {
        store.clearDirty();
        const target = navBtn.getAttribute("data-nav");
        if (target === "projects") {
          store.navigate("projects", { projectId: "" });
        } else if (target === "profiles") {
          store.setRoute("profiles");
        } else if (target === "storage") {
          store.navigate("settings", { settingsTab: "storage" });
        } else {
          store.navigate(target);
        }
        closeMobileRail();
        return;
      }

      if (ev.target.closest('[data-action="open-create-project"]')) {
        closeMobileRail();
        showCreateProjectModal();
        return;
      }

      const togBtn = ev.target.closest("[data-toggle-project]");
      if (togBtn) {
        store.toggleProjectExpand(togBtn.getAttribute("data-toggle-project"));
        return;
      }

      const openProj = ev.target.closest("[data-open-project]");
      if (openProj) {
        store.clearDirty();
        store.openProject(openProj.getAttribute("data-open-project"));
        closeMobileRail();
        return;
      }

      const openTask = ev.target.closest("[data-open-task]");
      if (openTask) {
        store.clearDirty("task-inputs");
        store.openTask(openTask.getAttribute("data-open-task"));
        closeMobileRail();
      }
    },
    { signal }
  );

  feedbackEl?.addEventListener(
    "click",
    (ev) => {
      if (ev.target.closest('[data-action="open-token-modal"]')) showTokenModal();
      if (ev.target.closest('[data-action="retry-connect"]')) store.refreshAll({ silent: false });
    },
    { signal }
  );

  // Input / Change tracking inside view
  viewEl?.addEventListener(
    "input",
    (ev) => {
      if (ev.target.id === "proj-search-input") {
        store.projectSearch = ev.target.value;
        render({ reason: "search" });
        return;
      }
      if (ev.target.id === "prof-search-input") {
        store.profileSearch = ev.target.value;
        render({ reason: "search" });
        return;
      }
      const dirtyWrap = ev.target.closest("[data-dirty-scope]");
      if (dirtyWrap) {
        store.markDirty(dirtyWrap.getAttribute("data-dirty-scope"));
      }
    },
    { signal }
  );

  viewEl?.addEventListener(
    "change",
    async (ev) => {
      const target = ev.target;
      const dirtyWrap = target.closest("[data-dirty-scope]");
      if (dirtyWrap) {
        store.markDirty(dirtyWrap.getAttribute("data-dirty-scope"));
      }

      // Live update read-only profile summary in Project Settings
      if (target.id === "ps-profile") {
        const preview = viewEl.querySelector("#proj-profile-preview");
        if (preview) {
          preview.innerHTML = renderProfileSummaryBoxHtml(target.value);
        }
        return;
      }

      // Profile tool risk override select
      if (target.hasAttribute("data-tool-risk") && profileDraft) {
        syncDraftInputsFromDom();
        const tname = target.getAttribute("data-tool-risk");
        const defRisk = target.getAttribute("data-default-risk") || "work";
        const val = target.value;
        const nextOverrides = { ...(profileDraft.tool_risk_overrides || {}) };
        if (val === "high") {
          nextOverrides[tname] = "high";
        } else if (defRisk === "high") {
          nextOverrides[tname] = "work";
        } else {
          delete nextOverrides[tname];
        }
        profileDraft.tool_risk_overrides = nextOverrides;
        store.markDirty("profile");
        return;
      }

      // Per-bot notification interval select
      if (target.hasAttribute("data-bot-interval")) {
        const umo = target.getAttribute("data-umo") || "";
        const enabled = target.getAttribute("data-enabled") === "1";
        const sec = Number(target.value || 30);
        try {
          await store.setProgress({ umo, enabled, min_interval_seconds: sec });
          store.toast("通知频率已保存", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
      }
    },
    { signal }
  );

  // View Click Delegation
  viewEl?.addEventListener(
    "click",
    async (ev) => {
      // Plugin card header outer switch: must NOT toggle <details>
      const pluginSwitch = ev.target.closest("[data-toggle-plugin]");
      if (pluginSwitch) {
        ev.preventDefault();
        ev.stopPropagation();
        if (pluginSwitch.disabled || !profileDraft) return;
        syncDraftInputsFromDom();
        const plugId = pluginSwitch.getAttribute("data-toggle-plugin");
        const bl = new Set(profileDraft.plugin_blacklist || []);
        if (bl.has(plugId)) {
          bl.delete(plugId);
        } else {
          bl.add(plugId);
        }
        profileDraft.plugin_blacklist = [...bl];
        store.markDirty("profile");
        render({ reason: "plugin-toggle" });
        return;
      }

      // Per-tool switch inside plugin card
      const toolSwitch = ev.target.closest("[data-toggle-tool]");
      if (toolSwitch) {
        ev.preventDefault();
        ev.stopPropagation();
        if (toolSwitch.disabled || !profileDraft) return;
        syncDraftInputsFromDom();
        const tname = toolSwitch.getAttribute("data-toggle-tool");
        const dt = new Set(profileDraft.disabled_tools || []);
        if (dt.has(tname)) {
          dt.delete(tname);
        } else {
          dt.add(tname);
        }
        profileDraft.disabled_tools = [...dt];
        store.markDirty("profile");
        render({ reason: "tool-toggle" });
        return;
      }

      const btn = ev.target.closest("button");
      if (!btn) {
        const profileTrigger = ev.target.closest(".profile-list-main[data-select-profile]");
        if (profileTrigger && !ev.target.closest(".profile-list-actions")) {
          profileDraftId = "";
          store.selectProfile(profileTrigger.getAttribute("data-select-profile"));
        }
        return;
      }
      const action = btn.dataset.action;

      if (action === "back-projects") {
        store.clearDirty();
        store.navigate("projects", { projectId: "" });
        return;
      }
      if (action === "open-create-project") {
        showCreateProjectModal();
        return;
      }
      if (action === "open-create-task") {
        showCreateTaskModal(btn.dataset.projectId || store.selectedProjectId);
        return;
      }
      if (action === "open-reconcile") {
        showReconcileModal(btn.dataset.taskId, btn.dataset.callId, btn.dataset.toolName);
        return;
      }
      if (action === "send-steer") {
        const input = viewEl.querySelector("#task-steer-input");
        const txt = input?.value.trim() || "";
        if (!txt) return store.toast("请输入引导指令", "error");
        try {
          await store.steer(btn.dataset.taskId, txt);
          if (input) input.value = "";
          store.toast("已发送途中引导", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "draft-project-summary") {
        try {
          const res = await store.draftSummary(btn.dataset.projectId);
          const ed = viewEl.querySelector("#proj-summary-editor");
          if (ed && res.draft !== undefined) {
            ed.value = res.draft;
            store.markDirty("summary");
          }
          store.toast("已生成项目摘要草稿", "info");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "save-project-summary") {
        const text = viewEl.querySelector("#proj-summary-editor")?.value || "";
        try {
          await store.saveSummary(btn.dataset.projectId, text);
          store.toast("项目摘要已保存", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "save-sharing") {
        const pid = btn.dataset.projectId;
        try {
          await store.updateProject(pid, {
            sharing: {
              share_with_daily: Boolean(viewEl.querySelector("#share-with-daily")?.checked),
              daily_summary_chars: Number(viewEl.querySelector("#daily-summary-chars")?.value || 600),
              share_with_tasks: Boolean(viewEl.querySelector("#share-with-tasks")?.checked),
              task_summary_chars: Number(viewEl.querySelector("#task-summary-chars")?.value || 3000),
            },
          });
          store.toast("共享策略已保存", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "jump-edit-profile") {
        const profId = btn.dataset.profileId || viewEl.querySelector("#ps-profile")?.value || "";
        store.clearDirty();
        store.navigate("profiles", { profileId: profId });
        return;
      }

      // Profiles actions
      if (action === "back-profiles") {
        profileDraftId = "";
        store.selectProfile("");
        return;
      }
      if (action === "create-profile") {
        showCreateProfileModal();
        return;
      }
      if (action === "duplicate-profile") {
        const keepOverview = !store.selectedProfileId;
        try {
          await store.duplicateProfile(btn.dataset.profileId, "", { select: !keepOverview });
          profileDraftId = "";
          store.toast("已复制生成新方案", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "set-default-profile") {
        const prof = store.getProfile(btn.dataset.profileId);
        if (!prof) return;
        const keepOverview = !store.selectedProfileId;
        try {
          await store.saveProfile({ ...prof, is_default: true }, { select: !keepOverview });
          profileDraftId = "";
          store.toast("已设为默认方案", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "delete-profile") {
        const pid = btn.dataset.profileId;
        showConfirmModal({
          title: "删除方案",
          message: "确认删除该方案？已绑定此方案的项目将回退至系统默认方案。",
          confirmLabel: "确认删除",
          onConfirm: async () => {
            try {
              await store.deleteProfile(pid);
              profileDraftId = "";
              store.toast("方案已删除", "success");
            } catch (err) {
              store.toast(err.message, "error");
            }
          },
        });
        return;
      }
      if (action === "disable-all-plugins" && profileDraft) {
        syncDraftInputsFromDom();
        profileDraft.plugin_blacklist = (store.state.plugins || [])
          .filter((pl) => !pl.protected && pl.name)
          .map((pl) => pl.name);
        store.markDirty("profile");
        render({ reason: "disable-all" });
        return;
      }
      if (action === "enable-all-plugins" && profileDraft) {
        syncDraftInputsFromDom();
        profileDraft.plugin_blacklist = [];
        profileDraft.disabled_tools = [];
        profileDraft.enabled_tools = [];
        store.markDirty("profile");
        render({ reason: "enable-all" });
        return;
      }

      // Settings actions
      if (action === "set-default-bot") {
        const botId = btn.dataset.botId || "";
        try {
          await store.setDefaultBot(botId);
          store.toast("已设为默认 Bot", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "toggle-bot-progress") {
        const umo = btn.dataset.umo || "";
        const wasOn = btn.getAttribute("aria-checked") === "true";
        const interval = Number(btn.dataset.interval || 30);
        try {
          await store.setProgress({ umo, enabled: !wasOn, min_interval_seconds: interval });
          store.toast(!wasOn ? "已开启进展通知" : "已关闭进展通知", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }
      if (action === "open-cred-modal") {
        showCredentialModal(null);
        return;
      }
      if (action === "save-standalone-token") {
        const val = viewEl.querySelector("#set-standalone-token")?.value || "";
        await store.setTokenAndReconnect(val);
        store.toast("访问令牌已应用", "success");
        return;
      }

      // Record preview
      if (action === "read-record" || btn.dataset.relPath) {
        const relPath = btn.dataset.relPath || "";
        if (!relPath) return store.toast("缺少文件路径", "error");
        return showReadRecordModal(relPath, btn.dataset.taskId || "");
      }

      // Cleanup
      if (btn.dataset.cleanupScope) {
        return showCleanupModal(btn.dataset.cleanupScope, {
          project_id: btn.dataset.projectId || "",
          task_id: btn.dataset.taskId || "",
        });
      }

      // Navigation & Tab switches
      if (btn.dataset.openProject) {
        store.clearDirty();
        return store.openProject(btn.dataset.openProject);
      }
      if (btn.dataset.projectTab) {
        store.clearDirty();
        store.projectTab = btn.dataset.projectTab;
        return render({ reason: "tab" });
      }
      if (btn.dataset.settingsTab) {
        store.clearDirty();
        store.settingsTab = btn.dataset.settingsTab;
        return render({ reason: "settings-tab" });
      }
      if (btn.dataset.vaultFilter) {
        store.vaultFilter = btn.dataset.vaultFilter;
        return render({ reason: "vault-filter" });
      }
      if (btn.dataset.openTask) {
        store.clearDirty("task-inputs");
        return store.openTask(btn.dataset.openTask);
      }
      if (btn.dataset.selectProfile) {
        profileDraftId = "";
        store.selectProfile(btn.dataset.selectProfile);
        return;
      }

      // Vault Edit / Delete
      if (btn.dataset.editCred) {
        const c = (store.state.credentials || []).find((x) => x.credential_id === btn.dataset.editCred);
        if (c) showCredentialModal(c);
        return;
      }
      if (btn.dataset.deleteCred) {
        const cid = btn.dataset.deleteCred;
        showConfirmModal({
          title: "删除保险箱条目",
          message: "确认删除此条目？删除后不可恢复，关联项目将不再使用该内容。",
          confirmLabel: "确认删除",
          onConfirm: async () => {
            try {
              await store.deleteCredential(cid);
              store.toast("条目已删除", "success");
            } catch (err) {
              store.toast(err.message, "error");
            }
          },
        });
        return;
      }

      // Task actions
      if (btn.dataset.taskAction) {
        const tid = btn.dataset.taskId;
        const task = store.getTask(tid);
        const ta = btn.dataset.taskAction;
        try {
          if (ta === "activate") {
            await store.activateTask(tid);
            store.toast("已切换到此任务", "success");
          } else if (ta === "pause") {
            await store.pauseTask(tid);
            store.toast("任务已暂停", "success");
          } else if (ta === "resume") {
            await store.resumeTask(tid);
            store.toast("任务已继续执行", "success");
          } else if (ta === "deliver") {
            showInputModal({
              title: "按现状交付任务",
              label: "可选交付备注（留空自动使用当前摘要）",
              placeholder: "例如：核心功能已完成，按现状归档",
              confirmLabel: "确认交付",
              onSubmit: async (note) => {
                try {
                  await store.deliverTask(tid, note);
                  store.toast("任务已交付归档", "success");
                } catch (err) {
                  store.toast(err.message, "error");
                }
              },
            });
          } else if (ta === "stop") {
            showInputModal({
              title: "停止任务",
              label: "停止原因",
              defaultValue: "管理员停止任务",
              confirmLabel: "确认停止",
              danger: true,
              onSubmit: async (reason) => {
                try {
                  await store.stopTask(tid, reason || "管理员停止任务");
                  store.toast("任务已停止", "success");
                } catch (err) {
                  store.toast(err.message, "error");
                }
              },
            });
          } else if (ta === "move" && task) {
            return showMoveTaskModal(task);
          } else if (ta === "budget" && task) {
            return showBudgetModal(task);
          }
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }

      if (btn.dataset.approveId) {
        const aid = btn.dataset.approveId;
        const note = viewEl.querySelector(`[data-approval-note="${CSS.escape(aid)}"]`)?.value.trim() || "";
        try {
          await store.approve(btn.dataset.taskId, aid, btn.dataset.decision, note);
          store.toast(btn.dataset.decision === "approved" ? "已批准执行" : "已拒绝", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }

      if (btn.dataset.quickAnswer) {
        try {
          await store.answer(btn.dataset.taskId, btn.dataset.questionId, btn.dataset.quickAnswer);
          store.toast("已提交回答", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }

      if (btn.dataset.submitAnswer) {
        const qid = btn.dataset.submitAnswer;
        const ans = viewEl.querySelector(`[data-question-input="${CSS.escape(qid)}"]`)?.value.trim() || "";
        if (!ans) return store.toast("请输入回答内容", "error");
        try {
          await store.answer(btn.dataset.taskId, qid, ans);
          store.toast("已提交回答", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
      }
    },
    { signal }
  );

  // Keyboard support for clickable profile overview rows
  viewEl?.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const profileTrigger = ev.target.closest(".profile-list-main[data-select-profile]");
      if (profileTrigger) {
        ev.preventDefault();
        profileDraftId = "";
        store.selectProfile(profileTrigger.getAttribute("data-select-profile"));
      }
    },
    { signal }
  );

  // Form Submissions
  viewEl?.addEventListener(
    "submit",
    async (ev) => {
      if (ev.target.id === "proj-settings-form") {
        ev.preventDefault();
        const pid = ev.target.dataset.projectId;
        const proj = store.getProject(pid);
        if (!proj) return;
        const lines = (sel) =>
          String(viewEl.querySelector(sel)?.value || "")
            .split(/\r?\n/)
            .map((x) => x.trim())
            .filter(Boolean);
        const profileId = viewEl.querySelector("#ps-profile")?.value || proj.profile_id;
        const existingEs = proj.execution_settings || {};
        try {
          await store.updateProject(pid, {
            title: viewEl.querySelector("#ps-title")?.value.trim() || proj.title,
            category: viewEl.querySelector("#ps-category")?.value.trim() || "通用",
            profile_id: profileId,
            execution_settings: {
              ...existingEs,
              roots: lines("#ps-roots"),
              warnings: lines("#ps-warnings"),
              task_prompt: viewEl.querySelector("#ps-task-prompt")?.value.trim() || "",
              authorized_credentials: [...viewEl.querySelectorAll('input[name="ps-creds"]:checked')].map(
                (el) => el.value
              ),
            },
          });
          store.toast("项目设置已保存", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
        return;
      }

      if (ev.target.id === "profile-editor-form") {
        ev.preventDefault();
        const data = collectProfileForm();
        if (!data) return;
        try {
          await store.saveProfile(data);
          profileDraftId = "";
          store.toast("方案已保存", "success");
        } catch (err) {
          store.toast(err.message, "error");
        }
      }
    },
    { signal }
  );

  // Live 1s runtime counter
  runtimeTicker = setInterval(() => {
    const activeTask = store.getPrimaryActiveTask();
    const runtimeEl = document.getElementById("task-runtime");
    if (activeTask && runtimeEl && activeTask.status === "running") {
      runtimeEl.textContent = fmtDuration(activeTask.started_at, activeTask.ended_at);
    }
  }, 1000);

  const unsubView = store.subscribeView(({ reason }) => render({ reason }));
  render({ reason: "mount" });

  return {
    render,
    unmount() {
      unsubView();
      ac.abort();
      if (runtimeTicker) clearInterval(runtimeTicker);
      if (botPopover) botPopover.hidden = true;
      closeMobileRail();
      closeModal();
    },
  };
}
