import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BellRing,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  FileText,
  GitBranch,
  LayoutDashboard,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { api, bridge, getToken, saveToken, subscribeEvents } from "./api";
import { GraphEditor, normalizeGraph } from "./GraphEditor";
import { TaskMemory } from "./TaskMemory";
import { OutcomeReview } from "./OutcomeReview";
import { ScheduleStart } from "./ScheduleStart";
import { toolUnavailable, toolModeLabel } from "./toolAvailability";
import type { Graph, State, Task, Template, Step } from "./types";
import "@xyflow/react/dist/style.css";
import "./style.css";

const emptyState: State = {
  tasks: [],
  templates: [],
  providers: [],
  tools: [],
  config: {},
};
const statusNames: Record<string, string> = {
  queued: "排队中",
  draft: "待制定计划",
  planning: "正在规划",
  awaiting_plan_approval: "等待批准计划",
  plan_pending: "等待批准计划",
  waiting_plan: "等待批准计划",
  planned: "等待批准计划",
  ready: "等待批准计划",
  running: "执行中",
  paused: "已暂停",
  waiting_approval: "等待审批",
  awaiting_approval: "等待审批",
  waiting_acceptance: "等待验收",
  awaiting_acceptance: "等待验收",
  review: "等待验收",
  completed: "已完成",
  cancelled: "已取消",
  failed: "执行失败",
  blocked: "遇到阻塞",
  pending: "待执行",
  succeeded: "已完成",
  approved: "已批准",
  rejected: "已拒绝",
};
const terminal = new Set(["completed", "cancelled", "failed"]);
const pretty = (v: unknown) =>
  typeof v === "string" ? v : JSON.stringify(v, null, 2);
const lines = (v: string) =>
  v
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
const listText = (v?: string | string[]) =>
  Array.isArray(v) ? v.join("\n") : v || "";
const dateText = (v?: string) =>
  v
    ? new Date(v).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <i />
      {statusNames[value] || value}
    </span>
  );
}
function taskGraph(task: Task): Graph {
  if (task.graph?.nodes?.length)
    return normalizeGraph({
      ...task.graph,
      nodes: task.graph.nodes.map((n) => {
        const step = task.steps?.find((s) => s.id === n.id);
        return {
          ...n,
          data: { ...n.data, status: step?.status, summary: step?.summary },
        };
      }),
    });
  return {
    nodes: (task.steps || []).map((s, i) => ({
      id: s.id,
      position: { x: (i % 3) * 310, y: Math.floor(i / 3) * 180 },
      data: {
        kind: s.kind || (s.tool_name ? "tool" : "agent"),
        title: s.title,
        instruction: s.instruction,
        tool_name: s.tool_name,
        arguments: s.arguments,
        status: s.status,
        summary: s.summary,
      },
    })),
    edges: (task.steps || []).flatMap((s) =>
      (s.depends_on || []).map((id) => ({
        id: `${id}_${s.id}`,
        source: id,
        target: s.id,
      })),
    ),
  };
}
function graphSteps(graph: Graph): Step[] {
  return graph.nodes.map((n) => ({
    id: n.id,
    title: n.data.title,
    instruction: n.data.instruction,
    kind: n.data.kind,
    tool_name: n.data.tool_name,
    arguments: n.data.arguments,
    depends_on: graph.edges
      .filter((e) => e.target === n.id)
      .map((e) => e.source),
  }));
}
function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="modal-shade"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button onClick={onClose} title="关闭">
            <X size={18} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function App() {
  const [state, setState] = useState<State>(emptyState);
  const [route, setRoute] = useState<"tasks" | "templates" | "settings">(
    "tasks",
  );
  const [selectedId, setSelectedId] = useState("");
  const selectedRef = useRef("");
  selectedRef.current = selectedId;
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [connectionEpoch, setConnectionEpoch] = useState(0);
  const connectedRef = useRef(false);
  const stateRef = useRef(state);
  stateRef.current = state;
  const [createOpen, setCreateOpen] = useState(false);
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    run: () => Promise<void>;
  } | null>(null);
  const [filter, setFilter] = useState("active");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"plan" | "logs" | "context">("plan");
  const [editingPlan, setEditingPlan] = useState(false);
  const [editingVersion, setEditingVersion] = useState(0);
  const [steer, setSteer] = useState("");
  const [steerMode, setSteerMode] = useState("steer");
  const [template, setTemplate] = useState<Template | null>(null);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [editorKey, setEditorKey] = useState(0);
  const [token, setToken] = useState(getToken());
  const [registry, setRegistry] = useState<{
    custom_apis?: Record<string, unknown>[];
    credentials?: Record<string, unknown>[];
  } | null>(null);
  const [registryForm, setRegistryForm] = useState<{
    kind: "api" | "credential";
    value: string;
  } | null>(null);
  const task = state.tasks.find((t) => t.task_id === selectedId);
  const graph = useMemo(
    () => (task ? taskGraph(task) : { nodes: [], edges: [] }),
    [task],
  );
  const loadingRef = useRef(false);
  const refresh = useCallback(
    async (loud = false) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      try {
        const data = await api<State & { ok: boolean }>("/harness/state");
        let selectedTask: Task | undefined;
        if (selectedRef.current) {
          try {
            selectedTask = (
              await api<{ task: Task }>(
                `/harness/task?task_id=${encodeURIComponent(selectedRef.current)}`,
              )
            ).task;
          } catch {
            /* A deleted task is resolved by the state listing. */
          }
        }
        setState({
          ...emptyState,
          ...data,
          tasks: (data.tasks || []).map((t) =>
            t.task_id === selectedTask?.task_id ? selectedTask : t,
          ),
        });
        setLoaded(true);
        if (loud) {
          setError("");
          setNotice("状态已更新");
        }
      } catch (e) {
        if (loud || !loaded) setError((e as Error).message);
      } finally {
        loadingRef.current = false;
      }
    },
    [loaded],
  );
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const refreshTask = useCallback(async (taskId: string) => {
    const result = await api<{ task: Task }>(
      `/harness/task?task_id=${encodeURIComponent(taskId)}`,
    );
    setState((s) => {
      const existing = s.tasks.find((t) => t.task_id === taskId);
      if (existing && (existing.revision || 0) > (result.task.revision || 0))
        return s;
      return {
        ...s,
        tasks: existing
          ? s.tasks.map((t) => (t.task_id === taskId ? result.task : t))
          : [result.task, ...s.tasks],
      };
    });
  }, []);
  useEffect(() => {
    void refreshRef.current();
    let scheduled: ReturnType<typeof setTimeout> | undefined;
    const pendingTasks = new Set<string>();
    let draining = false;
    let stopped = false;
    const schedule = () => {
      if (scheduled || draining || stopped) return;
      scheduled = setTimeout(async () => {
        scheduled = undefined;
        draining = true;
        const ids = [...pendingTasks];
        pendingTasks.clear();
        const results = await Promise.allSettled(ids.map(refreshTask));
        if (results.some((r) => r.status === "rejected")) {
          connectedRef.current = false;
          setConnected(false);
        }
        draining = false;
        if (pendingTasks.size) schedule();
      }, 400);
    };
    const unsub = subscribeEvents(
      (event) => {
        const id = String(event.task_id || "");
        if (!id) return;
        if (event.kind === "task.deleted" || event.type === "task.deleted") {
          pendingTasks.delete(id);
          setState((s) => ({
            ...s,
            tasks: s.tasks.filter((t) => t.task_id !== id),
          }));
          return;
        }
        const existing = stateRef.current.tasks.find((t) => t.task_id === id);
        const eventTime = Date.parse(
          String(event.time || event.created_at || ""),
        );
        if (existing && eventTime <= Date.parse(existing.updated_at || ""))
          return;
        pendingTasks.add(id);
        schedule();
      },
      (value) => {
        connectedRef.current = value;
        setConnected(value);
      },
    );
    const timer = setInterval(() => {
      if (!document.hidden && !connectedRef.current) void refreshRef.current();
    }, 10000);
    return () => {
      stopped = true;
      unsub();
      clearInterval(timer);
      clearTimeout(scheduled);
    };
  }, [connectionEpoch, refreshTask]);
  useEffect(() => {
    if (selectedId)
      void refreshTask(selectedId).catch((e) => setError((e as Error).message));
  }, [selectedId, refreshTask]);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(id);
  }, [notice]);
  async function run(name: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(name);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function action(
    actionName: string,
    extra: Record<string, unknown> = {},
  ) {
    if (!task) return;
    const result = await api<{ task?: Task; message?: string }>(
      "/harness/action",
      {
        task_id: task.task_id,
        action: actionName,
        revision: task.revision,
        ...extra,
      },
    );
    if (result.task)
      setState((s) => ({
        ...s,
        tasks: s.tasks.map((t) =>
          t.task_id === result.task!.task_id ? { ...t, ...result.task! } : t,
        ),
      }));
    if (actionName === "delete") setSelectedId("");
    setNotice(result.message || "操作已提交");
    await refresh();
  }
  function selectTask(id: string) {
    setSelectedId(id);
    setEditingPlan(false);
    setSteer("");
    setTab("plan");
  }
  function openTemplate(value?: Template) {
    setTemplate(
      value
        ? JSON.parse(JSON.stringify(value))
        : {
            template_id: "",
            name: "未命名模板",
            description: "",
            graph: { nodes: [], edges: [] },
          },
    );
    let metadata: { name?: string; description?: string } = {};
    try {
      metadata = JSON.parse(
        sessionStorage.getItem(
          `agent_lab_template_meta:${value?.template_id || "new"}`,
        ) || "{}",
      );
    } catch {
      /* Use persisted template values. */
    }
    setTemplateName(metadata.name ?? value?.name ?? "未命名模板");
    setTemplateDescription(metadata.description ?? value?.description ?? "");
    setEditorKey((k) => k + 1);
  }
  useEffect(() => {
    if (!template) return;
    try {
      sessionStorage.setItem(
        `agent_lab_template_meta:${template.template_id || "new"}`,
        JSON.stringify({
          name: templateName,
          description: templateDescription,
        }),
      );
    } catch {
      /* Editing still works when storage is full. */
    }
  }, [template, templateName, templateDescription]);
  async function saveTemplate(g: Graph) {
    if (!templateName.trim()) throw new Error("请填写模板名称。");
    setBusy("保存模板");
    try {
      const result = await api<{ template: Template }>("/harness/template", {
        action: "save",
        template: {
          template_id: template?.template_id || undefined,
          name: templateName.trim(),
          description: templateDescription,
          graph: g,
          revision: template?.revision,
        },
      });
      if (result.template) setTemplate(result.template);
      setNotice("模板已保存");
      await refresh();
    } finally {
      setBusy("");
    }
  }
  const pending = (task?.approvals || []).filter(
    (a) => !a.status || a.status === "pending",
  );
  const unknownCalls = (task?.tool_calls || []).filter(
    (call) => call.status === "unknown",
  );
  const activeTasks = state.tasks.filter((t) => !terminal.has(t.status));
  const waitingTasks = state.tasks.filter((t) =>
    [
      "awaiting_plan_approval",
      "plan_pending",
      "waiting_plan",
      "planned",
      "ready",
      "waiting_approval",
      "awaiting_approval",
      "waiting_acceptance",
      "awaiting_acceptance",
      "review",
      "blocked",
    ].includes(t.status),
  );
  const shownTasks = state.tasks.filter(
    (t) =>
      (filter === "all" ||
        (filter === "active"
          ? !terminal.has(t.status)
          : terminal.has(t.status))) &&
      `${t.title} ${t.goal}`.toLowerCase().includes(search.toLowerCase()),
  );
  const planNeedsApproval =
    !!task &&
    task.steps?.length > 0 &&
    task.status === "awaiting_plan_approval";
  const canRevise =
    !!task &&
    ["paused", "awaiting_plan_approval", "blocked"].includes(task.status);
  const canAccept =
    !!task &&
    ["waiting_acceptance", "awaiting_acceptance", "review"].includes(
      task.status,
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setRoute("tasks");
            setSelectedId("");
          }}
        >
          <span className="brand-symbol">
            <GitBranch size={23} />
          </span>
          <span>
            Agent Lab<small>任务工作台</small>
          </span>
        </a>
        <div className="nav-section">工作空间</div>
        <nav>
          <button
            className={route === "tasks" ? "active" : ""}
            onClick={() => {
              setRoute("tasks");
            }}
          >
            <LayoutDashboard size={18} />
            任务<span>{activeTasks.length}</span>
          </button>
          <button
            className={route === "templates" ? "active" : ""}
            onClick={() => setRoute("templates")}
          >
            <GitBranch size={18} />
            流程模板
          </button>
          <button
            className={route === "settings" ? "active" : ""}
            onClick={() => {
              setRoute("settings");
              void run("读取集成", async () =>
                setRegistry(await api("/registry")),
              );
            }}
          >
            <Settings2 size={18} />
            连接与集成
          </button>
        </nav>
        <div className="sidebar-bottom">
          <span className={`connection ${connected ? "online" : ""}`}>
            <i />
            {connected ? "实时事件已连接" : "每 10 秒同步状态"}
          </span>
          <p>
            管理员工作台
            <br />
            先确认计划，再开始执行。
          </p>
          <span className="version">AGENT LAB / 0.3</span>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            工作空间 <ChevronRight size={14} />
            <strong>
              {route === "tasks"
                ? task
                  ? task.title || "任务详情"
                  : "任务"
                : route === "templates"
                  ? "流程模板"
                  : "连接与集成"}
            </strong>
          </div>
          <div className="topbar-actions">
            <button
              title="刷新状态"
              disabled={!!busy}
              onClick={() => void run("刷新", () => refresh(true))}
            >
              <RefreshCw size={16} />
              <span>刷新</span>
            </button>
            <button
              className="primary"
              disabled={!!busy}
              onClick={() => setCreateOpen(true)}
            >
              <Plus size={16} />
              新建任务
            </button>
          </div>
        </header>
        {error && (
          <div className="banner error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError("")} title="关闭错误">
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="toast" role="status">
            <CheckCircle2 size={17} />
            {notice}
          </div>
        )}
        {!loaded && !error && (
          <div className="empty">
            <Loader2 className="spin" />
            <h2>正在读取任务</h2>
          </div>
        )}
        {route === "tasks" && !task && (
          <section className="page">
            <div className="page-title">
              <div>
                <div className="eyebrow">YOUR WORK, IN PROGRESS</div>
                <h1>让任务有始有终。</h1>
                <p>在这里批准计划、查看执行证据，并在需要时接手。</p>
              </div>
              <div className="stat-strip">
                <div>
                  <strong>{activeTasks.length}</strong>
                  <span>进行中</span>
                </div>
                <div>
                  <strong>{waitingTasks.length}</strong>
                  <span>等待处理</span>
                </div>
                <div>
                  <strong>
                    {state.tasks.filter((t) => t.status === "completed").length}
                  </strong>
                  <span>已完成</span>
                </div>
              </div>
            </div>
            <div className="list-toolbar">
              <div className="segmented">
                {[
                  ["active", "进行中"],
                  ["archived", "已结束"],
                  ["all", "全部"],
                ].map(([id, text]) => (
                  <button
                    key={id}
                    className={filter === id ? "active" : ""}
                    onClick={() => setFilter(id)}
                  >
                    {text}
                  </button>
                ))}
              </div>
              <input
                className="search"
                aria-label="搜索任务"
                placeholder="搜索任务目标…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="task-list">
              {shownTasks.map((t) => (
                <button
                  className="task-row"
                  key={t.task_id}
                  onClick={() => selectTask(t.task_id)}
                >
                  <span
                    className={`task-icon ${t.status === "completed" ? "done" : ""}`}
                  >
                    {t.status === "completed" ? (
                      <Check size={20} />
                    ) : (
                      <Activity size={20} />
                    )}
                  </span>
                  <span className="task-row-main">
                    <strong>{t.title || t.goal || "未命名任务"}</strong>
                    <span>{t.summary || t.goal}</span>
                  </span>
                  <Status value={t.status} />
                  <span className="task-date">
                    {dateText(t.updated_at || t.created_at)}
                  </span>
                  <ChevronRight size={17} />
                </button>
              ))}
              {!shownTasks.length && (
                <div className="empty">
                  <BookOpen size={34} />
                  <h2>
                    {state.tasks.length
                      ? "没有符合条件的任务"
                      : "从一个具体目标开始"}
                  </h2>
                  <p>写清楚要做什么、边界在哪里、怎样算完成。</p>
                  <button
                    className="primary"
                    onClick={() => setCreateOpen(true)}
                  >
                    <Plus size={16} />
                    创建第一个任务
                  </button>
                </div>
              )}
            </div>
            {!!state.legacy_tasks?.length && (
              <details className="legacy">
                <summary>旧版任务记录（{state.legacy_tasks.length}）</summary>
                <p>旧版记录保留供查阅；新工作台使用独立任务计划。</p>
                {state.legacy_tasks.map((t, i) => (
                  <pre key={i}>{pretty(t)}</pre>
                ))}
              </details>
            )}
          </section>
        )}
        {route === "tasks" && task && (
          <section className="task-page">
            <div className="task-heading">
              <button
                className="back"
                onClick={() => {
                  setSelectedId("");
                  setEditingPlan(false);
                }}
              >
                <ArrowLeft size={16} />
                全部任务
              </button>
              <div className="task-heading-row">
                <div>
                  <div className="eyebrow">TASK / {task.task_id}</div>
                  <h1>{task.title || task.goal}</h1>
                </div>
                <Status value={task.status} />
              </div>
              <p className="task-goal">{task.goal}</p>
              <div className="task-action-bar">
                <div className="toolbar-group">
                  {planNeedsApproval && (
                    <button
                      className="primary"
                      disabled={!!busy || editingPlan}
                      onClick={() =>
                        setConfirm({
                          title: "批准当前计划并开始执行",
                          message: `将按第 ${task.plan_version} 版计划执行 ${task.steps.length} 个步骤。请先确认工具参数、工作目录和验收条件。`,
                          run: () =>
                            action("approve_plan", {
                              plan_version: task.plan_version,
                            }),
                        })
                      }
                    >
                      <Play size={15} />
                      批准计划并执行
                    </button>
                  )}
                  {["running", "queued", "planning"].includes(task.status) && (
                    <button
                      disabled={!!busy}
                      onClick={() =>
                        void run("暂停任务", () => action("pause"))
                      }
                    >
                      <Pause size={15} />
                      暂停
                    </button>
                  )}
                  {["paused", "blocked"].includes(task.status) &&
                    !task.schedule_armed &&
                    !planNeedsApproval && (
                      <button
                        className="primary"
                        disabled={
                          !!busy ||
                          editingPlan ||
                          !!pending.length ||
                          !!unknownCalls.length
                        }
                        onClick={() =>
                          void run("恢复任务", () => action("resume"))
                        }
                      >
                        <Play size={15} />
                        恢复执行
                      </button>
                    )}
                  {canAccept && (
                    <button
                      className="primary"
                      disabled={!!busy}
                      onClick={() =>
                        setConfirm({
                          title: "验收任务",
                          message:
                            "确认执行结果满足下面的验收条件后，任务会标记为完成。",
                          run: () => action("accept"),
                        })
                      }
                    >
                      <CheckCircle2 size={15} />
                      验收通过
                    </button>
                  )}
                  {!terminal.has(task.status) && (
                    <button
                      disabled={!!busy}
                      onClick={() =>
                        setConfirm({
                          title: "取消任务",
                          message:
                            "请求停止后续执行并保留已有记录。已经产生的外部操作不会自动撤销。",
                          run: () => action("cancel"),
                        })
                      }
                    >
                      <Square size={14} />
                      取消任务
                    </button>
                  )}
                  {terminal.has(task.status) && (
                    <button
                      className="danger-text"
                      disabled={!!busy}
                      onClick={() =>
                        setConfirm({
                          title: "删除这条任务记录",
                          message: `仅删除任务「${task.title || task.task_id}」及其记录。此操作不可撤销。`,
                          run: () => action("delete"),
                        })
                      }
                    >
                      <Trash2 size={15} />
                      删除记录
                    </button>
                  )}
                </div>
                <span className="subtle">
                  计划 v{task.plan_version} ·{" "}
                  {task.execution_mode === "direct" ? "直接执行" : "沙箱执行"}
                </span>
              </div>
            </div>
            <div className="task-layout">
              <div className="task-main">
                <div className="tabs">
                  {[
                    ["plan", "执行计划", GitBranch],
                    ["logs", "事件记录", FileText],
                    ["context", "任务约定", ShieldCheck],
                  ].map(([id, text, Icon]) => {
                    const C = Icon as typeof GitBranch;
                    return (
                      <button
                        key={id as string}
                        className={tab === id ? "active" : ""}
                        onClick={() => setTab(id as typeof tab)}
                      >
                        <C size={16} />
                        {text as string}
                      </button>
                    );
                  })}
                </div>
                {tab === "plan" && (
                  <>
                    <div className="plan-intro">
                      <span>
                        {editingPlan
                          ? "修改后会产生新版本，需要重新批准。"
                          : "点击步骤查看执行要求与结果。"}
                      </span>
                      {canRevise && (
                        <button
                          disabled={!!busy}
                          onClick={() => {
                            if (editingPlan)
                              sessionStorage.removeItem(
                                `agent_lab_draft:task:${task.task_id}:${editingVersion}`,
                              );
                            if (!editingPlan)
                              setEditingVersion(task.plan_version);
                            setEditingPlan((v) => !v);
                          }}
                        >
                          {editingPlan ? "放弃本次修改" : "修订计划"}
                        </button>
                      )}
                      {task.status === "running" && (
                        <span className="subtle">
                          需要改计划时，先暂停任务。
                        </span>
                      )}
                      {!!task.steps?.length && !editingPlan && (
                        <button
                          disabled={!!busy}
                          onClick={() => {
                            sessionStorage.removeItem(
                              "agent_lab_draft:template:new",
                            );
                            openTemplate({
                              template_id: "",
                              name: `${task.title || "任务"}流程`,
                              description: task.goal,
                              graph: {
                                ...graph,
                                nodes: graph.nodes.map((n) => ({
                                  ...n,
                                  data: {
                                    ...n.data,
                                    status: undefined,
                                    summary: undefined,
                                  },
                                })),
                              },
                            });
                            setRoute("templates");
                          }}
                        >
                          另存为模板
                        </button>
                      )}
                    </div>
                    {editingPlan && editingVersion !== task.plan_version && (
                      <div className="note warning">
                        服务器计划已更新到 v{task.plan_version}，当前草稿基于 v
                        {editingVersion}
                        。提交时会检查冲突；请先保存草稿内容，再放弃本次修改并重新编辑。
                      </div>
                    )}
                    <GraphEditor
                      key={`${task.task_id}-${editingPlan ? "edit" : "read"}-${editingPlan ? editingVersion : ""}`}
                      draftKey={
                        editingPlan
                          ? `task:${task.task_id}:${editingVersion}`
                          : undefined
                      }
                      initial={graph}
                      editable={editingPlan}
                      executionMode={task.execution_mode}
                      tools={state.tools}
                      busy={!!busy}
                      label="提交修订计划"
                      onSave={
                        editingPlan
                          ? async (g) => {
                              setBusy("修订计划");
                              try {
                                await action("revise_plan", {
                                  plan_version: editingVersion,
                                  steps: graphSteps(g),
                                  graph: g,
                                });
                                setEditingPlan(false);
                              } finally {
                                setBusy("");
                              }
                            }
                          : undefined
                      }
                      description={`执行计划 v${task.plan_version}`}
                    />
                    <div className="step-results">
                      {(task.steps || []).map((s, i) => (
                        <details key={s.id}>
                          <summary>
                            <span className="step-number">{i + 1}</span>
                            <strong>{s.title}</strong>
                            <Status value={s.status || "pending"} />
                          </summary>
                          <p>{s.instruction}</p>
                          {s.summary && <div className="note">{s.summary}</div>}
                          {s.evidence !== undefined && (
                            <>
                              <h4>执行证据</h4>
                              <pre>{pretty(s.evidence)}</pre>
                            </>
                          )}
                        </details>
                      ))}
                    </div>
                  </>
                )}
                {tab === "logs" && (
                  <div className="event-list">
                    {(task.events || []).length ? (
                      (task.events || [])
                        .slice()
                        .reverse()
                        .map((e, i) => (
                          <article className="event" key={String(e.id || i)}>
                            <span className="event-dot" />
                            <div>
                              <div className="event-title">
                                <strong>
                                  {String(e.kind || e.type || "任务事件")}
                                </strong>
                                <time>
                                  {dateText(
                                    String(e.time || e.created_at || ""),
                                  )}
                                </time>
                              </div>
                              <pre>{pretty(e.payload ?? e.message ?? e)}</pre>
                            </div>
                          </article>
                        ))
                    ) : (
                      <div className="empty">
                        <FileText size={28} />
                        <h3>暂无事件记录</h3>
                        <p>计划和执行中的状态变化会记录在这里。</p>
                      </div>
                    )}
                  </div>
                )}
                {tab === "context" && (
                  <div className="context-grid">
                    <article>
                      <h3>执行边界</h3>
                      <pre>
                        {listText(task.constraints) || "未补充额外约束"}
                      </pre>
                    </article>
                    <article>
                      <h3>验收条件</h3>
                      <pre>{listText(task.acceptance) || "未补充验收条件"}</pre>
                    </article>
                    <article>
                      <h3>运行环境</h3>
                      <dl>
                        <dt>工作目录</dt>
                        <dd>{task.workspace || "由运行环境指定"}</dd>
                        <dt>来源会话</dt>
                        <dd>{task.source_umo || "管理员工作台"}</dd>
                        <dt>模型</dt>
                        <dd>{task.provider_id || "默认模型"}</dd>
                        <dt>负责人</dt>
                        <dd>{task.owner_id || "管理员"}</dd>
                        <dt>项目标识</dt>
                        <dd>{task.project_key || "未关联项目"}</dd>
                      </dl>
                    </article>
                    <TaskMemory
                      key={task.task_id}
                      task={task}
                      busy={!!busy}
                      onSave={async (text, shared) => {
                        let saved = false;
                        await run("保存任务资料", async () => {
                          await api("/harness/memory", {
                            task_id: task.task_id,
                            text,
                            status: "accepted",
                            share_with_project: shared,
                          });
                          await refreshTask(task.task_id);
                          setNotice("任务资料已保存");
                          saved = true;
                        });
                        return saved;
                      }}
                    />
                  </div>
                )}
              </div>
              <aside className="task-side">
                <ScheduleStart
                  key={task.task_id}
                  task={task}
                  busy={
                    !!busy ||
                    editingPlan ||
                    !!pending.length ||
                    !!unknownCalls.length
                  }
                  onCancel={() => run("取消定时安排", () => action("pause"))}
                  onSchedule={async (runAt) => {
                    setConfirm({
                      title: "批准计划并定时执行",
                      message: `将在 ${new Date(runAt).toLocaleString("zh-CN", { timeZoneName: "short" })} 执行当前 v${task.plan_version} 计划。请确认执行边界和步骤已审阅。`,
                      run: () =>
                        action("schedule", {
                          run_at: runAt,
                          plan_version: task.plan_version,
                        }),
                    });
                  }}
                />
                {unknownCalls.length > 0 && (
                  <section className="approval-section">
                    <h3>核对未确定的工具结果</h3>
                    {unknownCalls.map((call) => (
                      <OutcomeReview
                        key={String(call.intent_id)}
                        call={call}
                        busy={
                          !!busy ||
                          ["queued", "planning", "running"].includes(
                            task.status,
                          )
                        }
                        onSave={(outcome, note) =>
                          run("记录工具结果", () =>
                            action("reconcile_tool", {
                              intent_id: call.intent_id,
                              outcome,
                              note,
                            }),
                          )
                        }
                      />
                    ))}
                  </section>
                )}
                <section>
                  <div className="eyebrow">CURRENT STATE</div>
                  <h3>当前进展</h3>
                  <p>{task.summary || "任务已创建，等待计划与执行记录。"}</p>
                  {task.next_action && (
                    <div className="next-action">
                      <ArrowRight size={16} />
                      <span>{task.next_action}</span>
                    </div>
                  )}
                </section>
                {pending.length > 0 && (
                  <section className="approval-section">
                    <h3>
                      <BellRing size={17} />
                      需要你的批准
                    </h3>
                    {pending.map((a, i) => (
                      <div
                        className="approval"
                        key={String(a.approval_id || a.id || i)}
                      >
                        <strong>
                          {String(
                            a.title || a.tool_name || a.action || "待审批操作",
                          )}
                        </strong>
                        <pre>{pretty(a)}</pre>
                        <div className="toolbar-group">
                          <button
                            className="primary"
                            disabled={!!busy}
                            onClick={() =>
                              void run("批准操作", () =>
                                action("approve_tool", {
                                  approval_id: a.approval_id || a.id,
                                }),
                              )
                            }
                          >
                            批准
                          </button>
                          <button
                            disabled={!!busy}
                            onClick={() =>
                              void run("拒绝操作", () =>
                                action("reject_tool", {
                                  approval_id: a.approval_id || a.id,
                                }),
                              )
                            }
                          >
                            拒绝
                          </button>
                        </div>
                      </div>
                    ))}
                  </section>
                )}
                {!terminal.has(task.status) && (
                  <section>
                    <h3>
                      <MessageSquare size={17} />
                      途中指导
                    </h3>
                    <p className="subtle">
                      补充事实、纠正方向或提供新约束。每条指导都会保留记录。
                    </p>
                    <textarea
                      rows={5}
                      placeholder="例如：优先处理 Windows 环境，先不修改生产配置。"
                      value={steer}
                      onChange={(e) => setSteer(e.target.value)}
                      disabled={!!busy}
                    />
                    <label>
                      处理时机
                      <select
                        value={steerMode}
                        onChange={(e) => setSteerMode(e.target.value)}
                      >
                        <option value="steer">下一次决策前引导</option>
                        <option value="followup">
                          登记后续任务，不自动执行
                        </option>
                        <option value="inject">补充资料，不唤醒执行</option>
                      </select>
                    </label>
                    <button
                      className="full"
                      disabled={!!busy || !steer.trim()}
                      onClick={() =>
                        void run("发送指导", async () => {
                          await action("steer", {
                            message: steer.trim(),
                            mode: steerMode,
                          });
                          setSteer("");
                        })
                      }
                    >
                      <MessageSquare size={15} />
                      提交指导
                    </button>
                  </section>
                )}
                {!!task.inbox?.length && (
                  <section>
                    <h3>指导记录</h3>
                    {task.inbox.map((i, n) => (
                      <div className="inbox-item" key={String(i.id || n)}>
                        <p>{String(i.message || i.text || "")}</p>
                        <small>{String(i.status || "已提交")}</small>
                      </div>
                    ))}
                  </section>
                )}
                {!!task.followups?.length && (
                  <section>
                    <h3>后续任务请求</h3>
                    <p className="subtle">已留档，尚未创建或自动执行。</p>
                    {task.followups.map((item, i) => (
                      <div className="inbox-item" key={String(item.id || i)}>
                        <p>{String(item.message || "")}</p>
                        <small>{dateText(String(item.created_at || ""))}</small>
                      </div>
                    ))}
                  </section>
                )}
              </aside>
            </div>
          </section>
        )}
        {route === "templates" && (
          <section className={`page ${template ? "template-edit-page" : ""}`}>
            <div className="page-title compact">
              <div>
                <div className="eyebrow">REUSABLE WORKFLOWS</div>
                <h1>{template ? "编辑流程模板" : "流程模板"}</h1>
                <p>模板定义可复用步骤；执行时生成独立的任务计划。</p>
              </div>
              <button
                onClick={() => (template ? setTemplate(null) : openTemplate())}
              >
                {template ? <ArrowLeft size={16} /> : <Plus size={16} />}{" "}
                {template ? "返回模板库" : "新建模板"}
              </button>
            </div>
            {template ? (
              <>
                <div className="template-meta">
                  <label>
                    模板名称
                    <input
                      value={templateName}
                      onChange={(e) => setTemplateName(e.target.value)}
                    />
                  </label>
                  <label>
                    用途说明
                    <input
                      value={templateDescription}
                      onChange={(e) => setTemplateDescription(e.target.value)}
                    />
                  </label>
                </div>
                <GraphEditor
                  key={editorKey}
                  draftKey={`template:${template.template_id || "new"}`}
                  initial={template.graph}
                  editable
                  tools={state.tools}
                  busy={!!busy}
                  onSave={saveTemplate}
                />
              </>
            ) : (
              <div className="template-grid">
                {state.templates.map((t) => (
                  <article className="template-card" key={t.template_id}>
                    <span className="template-icon">
                      <GitBranch size={22} />
                    </span>
                    <h3>{t.name}</h3>
                    <p>{t.description || "可复用任务流程"}</p>
                    <span className="subtle">
                      {t.graph?.nodes?.length || 0} 个步骤
                    </span>
                    <div className="template-card-actions">
                      <button onClick={() => openTemplate(t)}>
                        编辑模板
                        <ArrowRight size={14} />
                      </button>
                      <button
                        title="删除模板"
                        disabled={!!busy}
                        onClick={() =>
                          setConfirm({
                            title: "删除模板",
                            message: `删除「${t.name}」不会删除已创建的任务。`,
                            run: async () => {
                              await api("/harness/template", {
                                action: "delete",
                                template: { template_id: t.template_id },
                              });
                              await refresh();
                              setNotice("模板已删除");
                            },
                          })
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </article>
                ))}
                <button
                  className="template-card add-template"
                  onClick={() => openTemplate()}
                >
                  <Plus size={28} />
                  <strong>创建流程模板</strong>
                  <span>模型步骤、工具调用、人工审批</span>
                </button>
              </div>
            )}
          </section>
        )}
        {route === "settings" && (
          <section className="page settings-page">
            <div className="page-title compact">
              <div>
                <div className="eyebrow">CONNECTIONS & CAPABILITIES</div>
                <h1>连接与集成</h1>
                <p>沿用 AstrBot 的模型与工具，并保留已有 API 和凭证配置。</p>
              </div>
            </div>
            <div className="settings-grid">
              <article className="settings-card">
                <h3>工作台连接</h3>
                <p>
                  {bridge()
                    ? "当前使用 AstrBot 原生页面登录态。"
                    : "当前使用独立控制台。令牌只保存在本标签页会话中。"}
                </p>
                {!bridge() && (
                  <>
                    <label>
                      独立控制台访问令牌
                      <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        autoComplete="off"
                      />
                    </label>
                    <button
                      onClick={() => {
                        saveToken(token);
                        connectedRef.current = false;
                        setConnected(false);
                        setConnectionEpoch((value) => value + 1);
                        void run("重新连接", () => refresh(true));
                      }}
                    >
                      保存令牌并连接
                    </button>
                  </>
                )}
                <p className="subtle">
                  任务状态和审批由后端检查。修改全局并发与运行预算，请使用
                  AstrBot 的插件配置。
                </p>
              </article>
              <article className="settings-card">
                <h3>已配置模型 · {state.providers.length}</h3>
                {state.providers.map((p) => (
                  <div className="integration-row" key={p.provider_id}>
                    <strong>{p.provider_id}</strong>
                    <span>{p.model}</span>
                  </div>
                ))}
                {!state.providers.length && (
                  <p className="subtle">
                    未发现模型，请先在 AstrBot 配置模型提供商。
                  </p>
                )}
              </article>
              <article className="settings-card">
                <div className="panel-heading">
                  <h3>凭证 · {registry?.credentials?.length || 0}</h3>
                  <button
                    onClick={() =>
                      setRegistryForm({
                        kind: "credential",
                        value: JSON.stringify(
                          { label: "", provider: "", scope: "api", value: "" },
                          null,
                          2,
                        ),
                      })
                    }
                  >
                    <Plus size={15} />
                    新增
                  </button>
                </div>
                {registry?.credentials?.map((c, i) => (
                  <div
                    className="integration-row"
                    key={String(c.credential_id || i)}
                  >
                    <span>
                      <strong>{String(c.label || c.credential_id)}</strong>
                      <small>{c.has_value ? "已保存密钥" : "未设置密钥"}</small>
                    </span>
                    <div className="toolbar-group">
                      <button
                        onClick={() =>
                          setRegistryForm({
                            kind: "credential",
                            value: JSON.stringify({ ...c, value: "" }, null, 2),
                          })
                        }
                      >
                        编辑
                      </button>
                      <button
                        title="删除凭证"
                        disabled={!!busy}
                        onClick={() =>
                          setConfirm({
                            title: "删除凭证",
                            message:
                              "引用这项凭证的 API 之后将无法认证。确认删除这项凭证？",
                            run: async () => {
                              await api("/registry", {
                                kind: "credential",
                                action: "delete",
                                item: { credential_id: c.credential_id },
                              });
                              setRegistry(await api("/registry"));
                              setNotice("凭证已删除");
                            },
                          })
                        }
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </article>
              <article className="settings-card">
                <div className="panel-heading">
                  <h3>自定义 API · {registry?.custom_apis?.length || 0}</h3>
                  <button
                    onClick={() =>
                      setRegistryForm({
                        kind: "api",
                        value: JSON.stringify(
                          {
                            name: "",
                            url: "",
                            method: "GET",
                            credential_id: "",
                            auth_type: "bearer",
                          },
                          null,
                          2,
                        ),
                      })
                    }
                  >
                    <Plus size={15} />
                    新增
                  </button>
                </div>
                {registry?.custom_apis?.map((c, i) => (
                  <div className="integration-row" key={String(c.api_id || i)}>
                    <span>
                      <strong>{String(c.name || c.api_id)}</strong>
                      <small>
                        {String(c.method || "GET")} {String(c.url || "")}
                      </small>
                    </span>
                    <div className="toolbar-group">
                      <button
                        onClick={() =>
                          setRegistryForm({
                            kind: "api",
                            value: JSON.stringify(c, null, 2),
                          })
                        }
                      >
                        编辑
                      </button>
                      <button
                        title="删除 API"
                        disabled={!!busy}
                        onClick={() =>
                          setConfirm({
                            title: "删除自定义 API",
                            message:
                              "引用这个 API 的流程需要更新后才能继续使用。确认删除？",
                            run: async () => {
                              await api("/registry", {
                                kind: "api",
                                action: "delete",
                                item: { api_id: c.api_id },
                              });
                              setRegistry(await api("/registry"));
                              await refresh();
                              setNotice("API 已删除");
                            },
                          })
                        }
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </article>
              <article className="settings-card wide">
                <h3>已注册工具 · {state.tools.length}</h3>
                <div className="tool-grid">
                  {state.tools.map((t) => (
                    <div key={t.name}>
                      <strong>{t.name}</strong>
                      <p>{t.description || "暂无说明"}</p>
                    </div>
                  ))}
                </div>
              </article>
            </div>
          </section>
        )}
      </main>
      {busy && (
        <div className="busy-chip" role="status">
          <Loader2 size={16} className="spin" />
          {busy}…
        </div>
      )}
      {createOpen && (
        <CreateTask
          state={state}
          busy={!!busy}
          onClose={() => !busy && setCreateOpen(false)}
          onCreate={(payload) =>
            run("创建任务", async () => {
              const result = await api<{ task: Task }>(
                "/harness/create",
                payload,
              );
              await refresh();
              if (result.task) {
                setState((s) => ({
                  ...s,
                  tasks: [
                    result.task,
                    ...s.tasks.filter((t) => t.task_id !== result.task.task_id),
                  ],
                }));
                selectTask(result.task.task_id);
              }
              setCreateOpen(false);
              setRoute("tasks");
              setNotice("任务已创建。检查计划后再批准执行。");
            })
          }
        />
      )}
      {confirm && (
        <Modal title={confirm.title} onClose={() => !busy && setConfirm(null)}>
          <p>{confirm.message}</p>
          <div className="modal-footer">
            <button disabled={!!busy} onClick={() => setConfirm(null)}>
              返回
            </button>
            <button
              className="primary"
              disabled={!!busy}
              onClick={() =>
                void run(confirm.title, async () => {
                  await confirm.run();
                  setConfirm(null);
                })
              }
            >
              {busy ? "处理中…" : "确认"}
            </button>
          </div>
        </Modal>
      )}
      {registryForm && (
        <Modal
          title={registryForm.kind === "api" ? "编辑自定义 API" : "编辑凭证"}
          onClose={() => !busy && setRegistryForm(null)}
        >
          <p className="subtle">
            使用已有注册表接口保存。凭证 value 留空保留原密钥；新凭证需填写
            value。
          </p>
          <textarea
            className="code registry-json"
            value={registryForm.value}
            onChange={(e) =>
              setRegistryForm({ ...registryForm, value: e.target.value })
            }
          />
          <div className="modal-footer">
            <button onClick={() => setRegistryForm(null)}>取消</button>
            <button
              className="primary"
              disabled={!!busy}
              onClick={() =>
                void run("保存集成", async () => {
                  const value = JSON.parse(registryForm.value);
                  if (
                    !value ||
                    Array.isArray(value) ||
                    typeof value !== "object"
                  )
                    throw new Error("请填写 JSON 对象");
                  await api("/registry", {
                    kind: registryForm.kind,
                    action: "save",
                    item: value,
                  });
                  setRegistry(await api("/registry"));
                  await refresh();
                  setRegistryForm(null);
                  setNotice("集成配置已保存");
                })
              }
            >
              保存
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function CreateTask({
  state,
  busy,
  onCreate,
  onClose,
}: {
  state: State;
  busy: boolean;
  onCreate: (payload: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    title: "",
    goal: "",
    source_umo: "",
    provider_id: state.providers[0]?.provider_id || "",
    execution_mode: String(state.config.default_execution_mode || "sandbox"),
    workspace: String(state.config.default_workspace || ""),
    project_key: "",
    constraints: "",
    acceptance: "",
    template_id: "",
  });
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [toolQuery, setToolQuery] = useState("");
  const templateToolProblems = (
    state.templates.find((t) => t.template_id === form.template_id)?.graph
      .nodes || []
  ).flatMap((node) => {
    if (node.data.kind !== "tool" || !node.data.tool_name) return [];
    const tool = state.tools.find((t) => t.name === node.data.tool_name);
    const reason = tool
      ? toolUnavailable(tool, form.execution_mode)
      : "工具不存在";
    return reason ? [`${node.data.tool_name}：${reason}`] : [];
  });
  const selectedToolProblems = allowedTools.flatMap((name) => {
    const tool = state.tools.find((t) => t.name === name);
    const reason = tool
      ? toolUnavailable(tool, form.execution_mode)
      : "工具不存在";
    return reason ? [`${name}：${reason}`] : [];
  });
  function field(key: keyof typeof form, value: string) {
    setForm((v) => ({ ...v, [key]: value }));
    if (key === "execution_mode")
      setAllowedTools((current) =>
        current.filter((name) => {
          const tool = state.tools.find((t) => t.name === name);
          return !!tool && !toolUnavailable(tool, value);
        }),
      );
  }
  return (
    <Modal title="新建任务" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (templateToolProblems.length || selectedToolProblems.length)
            return;
          void onCreate({
            ...form,
            title: form.title.trim() || form.goal.trim().slice(0, 36),
            constraints: lines(form.constraints),
            acceptance: lines(form.acceptance),
            template_id: form.template_id || undefined,
            allowed_tools: allowedTools,
          });
        }}
      >
        <p className="subtle">创建后先生成计划。批准之前不会开始执行。</p>
        <label>
          任务目标 <em>*</em>
          <textarea
            autoFocus
            required
            rows={3}
            placeholder="例如：检查项目的配置读取逻辑，提出改动并完成修复。"
            value={form.goal}
            onChange={(e) => field("goal", e.target.value)}
          />
        </label>
        <div className="form-grid">
          <label>
            任务名称
            <input
              placeholder="可选，默认从目标生成"
              value={form.title}
              onChange={(e) => field("title", e.target.value)}
            />
          </label>
          <label>
            起始模板
            <select
              value={form.template_id}
              onChange={(e) => {
                field("template_id", e.target.value);
                const picked = state.templates.find(
                  (t) => t.template_id === e.target.value,
                );
                if (picked)
                  setAllowedTools((current) => [
                    ...new Set([
                      ...current,
                      ...picked.graph.nodes.flatMap((n) =>
                        n.data.kind === "tool" && n.data.tool_name
                          ? [n.data.tool_name]
                          : [],
                      ),
                    ]),
                  ]);
              }}
            >
              <option value="">根据目标生成计划</option>
              {state.templates.map((t) => (
                <option key={t.template_id} value={t.template_id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            执行模型
            <select
              value={form.provider_id}
              onChange={(e) => field("provider_id", e.target.value)}
            >
              <option value="">使用默认模型</option>
              {state.providers.map((p) => (
                <option value={p.provider_id} key={p.provider_id}>
                  {p.provider_id} {p.model ? `· ${p.model}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            运行方式
            <select
              value={form.execution_mode}
              onChange={(e) => field("execution_mode", e.target.value)}
            >
              <option value="sandbox">沙箱执行</option>
              <option value="direct">直接执行</option>
            </select>
          </label>
        </div>
        <label>
          工作目录
          <input
            placeholder="运行环境中允许操作的目录"
            value={form.workspace}
            onChange={(e) => field("workspace", e.target.value)}
          />
        </label>
        <label>
          项目标识
          <input
            placeholder="例如 agent-lab；相关任务填写相同标识可共享已确认的项目经验"
            value={form.project_key}
            onChange={(e) => field("project_key", e.target.value)}
          />
        </label>
        {form.execution_mode === "direct" && (
          <div className="note warning">
            直接模式会在宿主环境调用工具，请明确填写操作边界。
          </div>
        )}
        <div className="form-grid">
          <label>
            执行约束
            <textarea
              rows={3}
              placeholder="一行一条，如：不修改生产配置"
              value={form.constraints}
              onChange={(e) => field("constraints", e.target.value)}
            />
          </label>
          <label>
            验收条件
            <textarea
              rows={3}
              placeholder="一行一条，如：列出修改文件及验证结果"
              value={form.acceptance}
              onChange={(e) => field("acceptance", e.target.value)}
            />
          </label>
        </div>
        <details className="tools-picker">
          <summary>指定工具范围（已选 {allowedTools.length}）</summary>
          <p className="subtle">
            留空使用核心工具；勾选后只开放所选工具。插件与 MCP
            工具需要直接模式，并在 AstrBot 插件配置中授权。注册 API 另行审批。
          </p>
          <input
            placeholder="搜索工具…"
            value={toolQuery}
            onChange={(e) => setToolQuery(e.target.value)}
          />
          <div className="tools-checklist">
            {state.tools
              .filter((t) =>
                `${t.name} ${t.description || ""}`
                  .toLowerCase()
                  .includes(toolQuery.toLowerCase()),
              )
              .map((t) => (
                <label key={t.name}>
                  <input
                    type="checkbox"
                    checked={allowedTools.includes(t.name)}
                    disabled={!!toolUnavailable(t, form.execution_mode)}
                    onChange={(e) =>
                      setAllowedTools((v) =>
                        e.target.checked
                          ? [...v, t.name]
                          : v.filter((n) => n !== t.name),
                      )
                    }
                  />
                  <span>
                    <strong>
                      {t.name}
                      {toolModeLabel(t.name)}
                    </strong>
                    {toolUnavailable(t, form.execution_mode) && (
                      <small>{toolUnavailable(t, form.execution_mode)}</small>
                    )}
                    <small>{t.description}</small>
                  </span>
                </label>
              ))}
          </div>
        </details>
        {(templateToolProblems.length > 0 ||
          selectedToolProblems.length > 0) && (
          <div className="note warning">
            当前模板或工具选择不能在此模式执行：
            {[
              ...new Set([...templateToolProblems, ...selectedToolProblems]),
            ].join("；")}
            。请调整模式、模板或管理员授权。
          </div>
        )}
        <details>
          <summary>关联聊天会话（可选）</summary>
          <label>
            会话来源 UMO
            <input
              placeholder="平台实例:消息类型:会话 ID"
              value={form.source_umo}
              onChange={(e) => field("source_umo", e.target.value)}
            />
          </label>
        </details>
        <div className="modal-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            type="submit"
            disabled={
              busy ||
              !form.goal.trim() ||
              !!templateToolProblems.length ||
              !!selectedToolProblems.length
            }
          >
            {busy ? "正在创建…" : "创建并制定计划"}
            <ArrowRight size={15} />
          </button>
        </div>
      </form>
    </Modal>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
