import { safeSessionGet, safeSessionSet, safeSessionRemove } from "./storage";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  reconnectEdge,
  type NodeProps,
  type Connection,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  Bot,
  Wrench,
  ShieldCheck,
  Undo2,
  Redo2,
  Trash2,
  Save,
  Plus,
  X,
  GitBranch,
} from "lucide-react";
import type { Graph, FlowNode, NodeData, Kind } from "./types";
import {
  toolUnavailable,
  toolModeLabel,
  type ToolRow,
} from "./toolAvailability";

const kindNames = { agent: "模型步骤", tool: "工具调用", approval: "人工审批" };
const NodeCard = memo(
  ({ data, selected, isConnectable }: NodeProps<FlowNode>) => {
    const Icon =
      data.kind === "tool"
        ? Wrench
        : data.kind === "approval"
          ? ShieldCheck
          : Bot;
    return (
      <div
        className={`flow-card ${selected ? "selected" : ""} kind-${data.kind}`}
      >
        <Handle
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
        />
        <div className="node-kind">
          <Icon size={14} />
          {kindNames[data.kind]}
          {data.status && <span>{data.status}</span>}
        </div>
        <strong>{data.title || "未命名步骤"}</strong>
        <p>
          {data.kind === "tool"
            ? data.tool_name || "请选择工具"
            : data.instruction || "点击配置步骤"}
        </p>
        <Handle
          type="source"
          position={Position.Right}
          isConnectable={isConnectable}
        />
      </div>
    );
  },
);
const nodeTypes = { lab: NodeCard };
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
export function normalizeGraph(graph?: Graph): Graph {
  return {
    nodes: (graph?.nodes || []).map((n) => ({
      ...n,
      type: "lab",
      position: n.position || { x: 0, y: 0 },
      data: { ...n.data },
    })),
    edges: (graph?.edges || []).map((e, i) => ({
      ...e,
      id: e.id || `edge_${i}`,
      type: "smoothstep",
    })),
  };
}
export function graphErrors(graph: Graph): string[] {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const errors: string[] = [];
  if (!graph.nodes.length) errors.push("请至少添加一个步骤。");
  if (graph.nodes.length > 100) errors.push("一个计划最多包含 100 个步骤。");
  if (ids.size !== graph.nodes.length) errors.push("步骤 ID 重复。");
  const adj = new Map<string, string[]>();
  graph.nodes.forEach((n) => adj.set(n.id, []));
  graph.edges.forEach((e) => {
    if (!ids.has(e.source) || !ids.has(e.target))
      errors.push("连线指向了不存在的步骤。");
    else adj.get(e.source)!.push(e.target);
  });
  const visiting = new Set<string>(),
    done = new Set<string>();
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (done.has(id)) return false;
    visiting.add(id);
    if ((adj.get(id) || []).some(visit)) return true;
    visiting.delete(id);
    done.add(id);
    return false;
  };
  if ([...ids].some(visit))
    errors.push("存在循环连线；任务计划必须是有向无环图。");
  graph.nodes.forEach((n) => {
    if (!n.data.title.trim()) errors.push("有步骤没有名称。");
    if (n.data.kind === "tool" && !n.data.tool_name)
      errors.push(`「${n.data.title}」尚未选择工具。`);
    if (n.data.kind !== "tool" && !n.data.instruction.trim())
      errors.push(`「${n.data.title}」尚未填写执行要求。`);
  });
  return [...new Set(errors)];
}
export function GraphEditor({
  initial,
  editable,
  tools,
  onSave,
  busy,
  label = "保存模板",
  description,
  draftKey,
  executionMode,
}: {
  initial: Graph;
  editable: boolean;
  tools: ToolRow[];
  onSave?: (graph: Graph) => Promise<void>;
  busy?: boolean;
  label?: string;
  description?: string;
  draftKey?: string;
  executionMode?: string;
}) {
  const [graph, setGraph] = useState(() => {
    if (editable && draftKey) {
      try {
        const saved = safeSessionGet(`agent_lab_draft:${draftKey}`);
        if (saved) return normalizeGraph(JSON.parse(saved));
      } catch {
        /* Keep the server snapshot if a draft is unavailable. */
      }
    }
    return normalizeGraph(initial);
  });
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const reconnectingRef = useRef("");
  const draggingRef = useRef(false);
  const instance = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null);
  const connectingFrom = useRef("");
  const [dropMenu, setDropMenu] = useState<{
    source: string;
    x: number;
    y: number;
    flow: { x: number; y: number };
  } | null>(null);
  const [selected, setSelected] = useState("");
  const [dirty, setDirty] = useState(() => {
    try {
      return !!draftKey && !!safeSessionGet(`agent_lab_draft:${draftKey}`);
    } catch {
      return false;
    }
  });
  const [past, setPast] = useState<Graph[]>([]);
  const [future, setFuture] = useState<Graph[]>([]);
  const [error, setError] = useState("");
  const [args, setArgs] = useState("{}");
  const [argsError, setArgsError] = useState("");
  useEffect(() => {
    if (!editable) setGraph(normalizeGraph(initial));
  }, [initial, editable]);
  useEffect(() => {
    if (!editable || !draftKey || !dirty || draggingRef.current) return;
    try {
      safeSessionSet(`agent_lab_draft:${draftKey}`, JSON.stringify(graph));
    } catch {
      /* A full browser store never prevents editing. */
    }
  }, [graph, editable, draftKey, dirty]);
  const node = graph.nodes.find((n) => n.id === selected);
  const errors = graphErrors(graph);
  for (const item of graph.nodes.filter(
    (n) => n.data.kind === "tool" && n.data.tool_name,
  )) {
    const tool = tools.find((t) => t.name === item.data.tool_name);
    const reason = tool ? toolUnavailable(tool, executionMode) : "工具已不可用";
    if (reason) errors.push(`「${item.data.title}」：${reason}`);
  }
  useEffect(() => {
    setArgs(
      JSON.stringify(
        graphRef.current.nodes.find((n) => n.id === selected)?.data.arguments ||
          {},
        null,
        2,
      ),
    );
    setArgsError("");
  }, [selected]);
  useEffect(() => {
    const prevent = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        !editable ||
        busy ||
        !(e.ctrlKey || e.metaKey) ||
        (e.target as HTMLElement)?.closest(
          "input, textarea, select, [contenteditable]",
        )
      )
        return;
      if (e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
      } else if (e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  function checkpoint() {
    setPast((p) => [...p.slice(-49), clone(graphRef.current)]);
    setFuture([]);
    setDirty(true);
  }
  function startDrag() {
    if (!editable || busy) return;
    draggingRef.current = true;
    checkpoint();
  }
  function finishDrag() {
    draggingRef.current = false;
    if (editable && draftKey) {
      try {
        safeSessionSet(
          `agent_lab_draft:${draftKey}`,
          JSON.stringify(graphRef.current),
        );
      } catch {
        /* Keep the in-memory edit. */
      }
    }
  }
  function mutate(fn: (g: Graph) => Graph) {
    checkpoint();
    setGraph(fn);
  }
  const changeNodes = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      if (
        (!editable || busy) &&
        changes.some((c) => c.type !== "select" && c.type !== "dimensions")
      )
        return;
      setGraph((g) => ({ ...g, nodes: applyNodeChanges(changes, g.nodes) }));
    },
    [editable, busy],
  );
  const changeEdges = useCallback(
    (changes: EdgeChange<Edge>[]) => {
      if ((!editable || busy) && changes.some((c) => c.type !== "select"))
        return;
      setGraph((g) => ({ ...g, edges: applyEdgeChanges(changes, g.edges) }));
    },
    [editable, busy],
  );
  const validConnection = (connection: Connection | Edge) => {
    if (
      !connection.source ||
      !connection.target ||
      connection.source === connection.target
    )
      return false;
    const base = graphRef.current;
    const replacedId =
      "id" in connection ? connection.id : reconnectingRef.current;
    const edges = base.edges.filter((e) => e.id !== replacedId);
    const candidate = {
      ...base,
      edges: [
        ...edges,
        {
          id: "candidate",
          source: connection.source,
          target: connection.target,
        },
      ],
    };
    return !graphErrors(candidate).some(
      (e) => e.includes("循环") || e.includes("不存在"),
    );
  };
  function connect(connection: Connection) {
    if (!editable || busy) return;
    if (!validConnection(connection)) {
      setError("不能创建循环或无效连线。");
      return;
    }
    mutate((g) => ({
      ...g,
      edges: addEdge({ ...connection, type: "smoothstep" }, g.edges),
    }));
    setError("");
  }
  function reconnect(edge: Edge, connection: Connection) {
    if (!editable || busy) return;
    const candidate = { ...connection, id: edge.id };
    if (!validConnection(candidate as Edge)) {
      setError("重接会产生循环，已保留原连线。");
      return;
    }
    mutate((g) => ({ ...g, edges: reconnectEdge(edge, connection, g.edges) }));
  }
  function add(kind: Kind, source = "", position?: { x: number; y: number }) {
    if (!editable || busy) return;
    const suffix =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID().slice(0, 8)
        : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
    const id = `step_${suffix}`;
    const count = graph.nodes.length;
    mutate((g) => ({
      ...g,
      nodes: [
        ...g.nodes,
        {
          id,
          type: "lab",
          position: position || {
            x: 100 + (count % 3) * 300,
            y: 80 + Math.floor(count / 3) * 170,
          },
          data: {
            kind,
            title: kindNames[kind],
            instruction: "",
            ...(kind === "tool" ? { arguments: {} } : {}),
          },
        },
      ],
      edges: source
        ? [
            ...g.edges,
            { id: `${source}_${id}`, source, target: id, type: "smoothstep" },
          ]
        : g.edges,
    }));
    setSelected(id);
    setDropMenu(null);
  }
  function update(data: Partial<NodeData>) {
    mutate((g) => ({
      ...g,
      nodes: g.nodes.map((n) =>
        n.id === selected ? { ...n, data: { ...n.data, ...data } } : n,
      ),
    }));
  }
  function removeSelected() {
    const ids = new Set(
      graph.nodes
        .filter((n) => n.selected || n.id === selected)
        .map((n) => n.id),
    );
    mutate((g) => ({
      nodes: g.nodes.filter((n) => !ids.has(n.id)),
      edges: g.edges.filter(
        (e) => !e.selected && !ids.has(e.source) && !ids.has(e.target),
      ),
    }));
    setSelected("");
  }
  function undo() {
    const target = past[past.length - 1];
    if (!target) return;
    setFuture((p) => [...p, clone(graph)]);
    setPast((p) => p.slice(0, -1));
    setGraph(target);
    setDirty(true);
    setSelected("");
  }
  function redo() {
    const target = future[future.length - 1];
    if (!target) return;
    setPast((p) => [...p, clone(graph)]);
    setFuture((p) => p.slice(0, -1));
    setGraph(target);
    setDirty(true);
    setSelected("");
  }
  return (
    <div className="graph-editor">
      <div className="graph-toolbar">
        <div className="toolbar-group">
          <GitBranch size={16} />
          <strong>{description || "流程编辑器"}</strong>
          <span className="subtle">
            {graph.nodes.length} 步骤 · {graph.edges.length} 连线
            {dirty ? " · 未保存" : ""}
          </span>
        </div>
        {editable && (
          <div className="toolbar-group">
            <button onClick={undo} disabled={!past.length || busy} title="撤销">
              <Undo2 size={16} />
            </button>
            <button
              onClick={redo}
              disabled={!future.length || busy}
              title="重做"
            >
              <Redo2 size={16} />
            </button>
            <button
              onClick={removeSelected}
              disabled={
                busy ||
                (!selected &&
                  !graph.edges.some((e) => e.selected) &&
                  !graph.nodes.some((n) => n.selected))
              }
              title="删除选中节点或连线"
            >
              <Trash2 size={16} />
            </button>
            {onSave && (
              <button
                className="primary"
                disabled={busy || !!errors.length || !!argsError}
                onClick={async () => {
                  try {
                    setError("");
                    await onSave({
                      nodes: graph.nodes.map(({ id, position, data }) => ({
                        id,
                        position,
                        data: {
                          kind: data.kind,
                          title: data.title,
                          instruction: data.instruction,
                          tool_name: data.tool_name,
                          arguments: data.arguments,
                        },
                      })),
                      edges: graph.edges.map(({ id, source, target }) => ({
                        id,
                        source,
                        target,
                      })),
                    });
                    setDirty(false);
                    if (draftKey)
                      safeSessionRemove(`agent_lab_draft:${draftKey}`);
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                <Save size={15} />
                {busy ? "提交中…" : label}
              </button>
            )}
          </div>
        )}
      </div>
      {(error || argsError) && (
        <div className="error inline">{error || argsError}</div>
      )}
      <div className="graph-body">
        <div className="graph-canvas">
          {editable && (
            <div className="node-palette">
              {(["agent", "tool", "approval"] as Kind[]).map((k) => (
                <button key={k} disabled={busy} onClick={() => add(k)}>
                  <Plus size={14} />
                  {kindNames[k]}
                </button>
              ))}
            </div>
          )}
          <ReactFlow
            onInit={(flow) => {
              instance.current = flow;
            }}
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            onNodesChange={changeNodes}
            onEdgesChange={changeEdges}
            onConnect={connect}
            onConnectStart={(_, params) => {
              connectingFrom.current =
                params.handleType === "source" ? params.nodeId || "" : "";
              setDropMenu(null);
            }}
            onConnectEnd={(event, connection) => {
              const source = connectingFrom.current;
              connectingFrom.current = "";
              if (
                !editable ||
                busy ||
                !source ||
                connection.isValid ||
                reconnectingRef.current
              )
                return;
              const target = event.target as HTMLElement;
              if (!target?.closest(".react-flow__pane")) return;
              const point =
                "changedTouches" in event ? event.changedTouches[0] : event;
              const flow = instance.current?.screenToFlowPosition({
                x: point.clientX,
                y: point.clientY,
              });
              if (flow)
                setDropMenu({
                  source,
                  x: point.clientX,
                  y: point.clientY,
                  flow,
                });
            }}
            onReconnect={reconnect}
            onReconnectStart={(_, edge) => {
              reconnectingRef.current = edge.id;
            }}
            onReconnectEnd={() => {
              reconnectingRef.current = "";
            }}
            onBeforeDelete={async () => {
              if (!editable || busy) return false;
              checkpoint();
              return true;
            }}
            isValidConnection={validConnection}
            onNodeClick={(_, n) => setSelected(n.id)}
            onEdgeClick={() => {
              setSelected("");
              setDropMenu(null);
            }}
            onPaneClick={() => {
              setSelected("");
              setDropMenu(null);
            }}
            onNodeDragStart={startDrag}
            onNodeDragStop={finishDrag}
            onSelectionDragStart={startDrag}
            onSelectionDragStop={finishDrag}
            nodesDraggable={editable && !busy}
            nodesConnectable={editable && !busy}
            edgesReconnectable={editable && !busy}
            deleteKeyCode={editable && !busy ? ["Backspace", "Delete"] : null}
            selectionOnDrag
            panOnDrag={[1, 2]}
            panActivationKeyCode="Space"
            selectionKeyCode="Shift"
            multiSelectionKeyCode={["Control", "Meta"]}
            fitView
            minZoom={0.15}
            maxZoom={2}
            onlyRenderVisibleElements
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) =>
                n.data.kind === "tool"
                  ? "#3976aa"
                  : n.data.kind === "approval"
                    ? "#b7842c"
                    : "#37866d"
              }
            />
          </ReactFlow>
          {editable && dropMenu && (
            <div
              className="connection-menu"
              style={{
                position: "fixed",
                left: Math.min(dropMenu.x, window.innerWidth - 180),
                top: Math.min(dropMenu.y, window.innerHeight - 165),
              }}
            >
              <strong>添加并连接下一步</strong>
              {(["agent", "tool", "approval"] as Kind[]).map((kind) => (
                <button
                  key={kind}
                  onClick={() => add(kind, dropMenu.source, dropMenu.flow)}
                >
                  <Plus size={13} />
                  {kindNames[kind]}
                </button>
              ))}
              <button onClick={() => setDropMenu(null)}>取消</button>
            </div>
          )}
          <div className="canvas-hint">
            {editable
              ? "拖节点 · 空格拖画布 · 拖空白框选 · 拖连线到空白处添加步骤"
              : "只读计划 · 点击步骤查看 · 空格拖画布"}
          </div>
        </div>
        <aside className="node-inspector">
          {node ? (
            <>
              <div className="panel-heading">
                <strong>步骤设置</strong>
                <button onClick={() => setSelected("")} title="关闭步骤设置">
                  <X size={16} />
                </button>
              </div>
              <label>
                名称
                <input
                  value={node.data.title}
                  disabled={!editable || busy}
                  onChange={(e) => update({ title: e.target.value })}
                />
              </label>
              <label>
                执行要求
                <textarea
                  rows={7}
                  value={node.data.instruction}
                  disabled={!editable || busy}
                  onChange={(e) => update({ instruction: e.target.value })}
                />
              </label>
              <span className="subtle">
                {kindNames[node.data.kind]} · {node.id}
              </span>
              {node.data.kind === "tool" && (
                <>
                  <label>
                    执行工具
                    <select
                      value={node.data.tool_name || ""}
                      disabled={!editable || busy}
                      onChange={(e) => update({ tool_name: e.target.value })}
                    >
                      <option value="">选择已注册工具</option>
                      {tools.map((t) => (
                        <option
                          key={t.name}
                          value={t.name}
                          disabled={!!toolUnavailable(t, executionMode)}
                        >
                          {t.name}
                          {toolModeLabel(t.name)}
                          {toolUnavailable(t, executionMode)
                            ? ` · ${toolUnavailable(t, executionMode)}`
                            : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="field-help">
                    {
                      tools.find((t) => t.name === node.data.tool_name)
                        ?.description
                    }
                  </p>
                  <label>
                    参数 JSON
                    <textarea
                      className="code"
                      rows={9}
                      value={args}
                      disabled={!editable || busy}
                      onChange={(e) => {
                        const text = e.target.value;
                        setArgs(text);
                        try {
                          const value = JSON.parse(text);
                          if (
                            !value ||
                            Array.isArray(value) ||
                            typeof value !== "object"
                          )
                            throw new Error();
                          update({ arguments: value });
                          setArgsError("");
                        } catch {
                          setArgsError(
                            "工具参数必须是合法的 JSON 对象，修正后才能保存。",
                          );
                        }
                      }}
                    />
                  </label>
                </>
              )}
              {node.data.summary && (
                <div className="note">{node.data.summary}</div>
              )}
            </>
          ) : (
            <>
              <div className="eyebrow">GRAPH EDITOR</div>
              <h3>{editable ? "把步骤连起来" : "本次任务计划"}</h3>
              <p className="subtle">
                {editable
                  ? "从顶部添加步骤，拖动输出端口连接下一步。选择节点编辑要求；按住 Shift 可以多选。"
                  : "选择步骤查看执行要求。运行中的计划不会被静默修改。"}
              </p>
            </>
          )}
          {editable && errors.length > 0 && (
            <div className="validation">
              <strong>待完善</strong>
              {errors.map((e) => (
                <p key={e}>{e}</p>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
