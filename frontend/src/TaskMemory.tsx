import { useState } from "react";
import { BookOpen, Save, ShieldCheck } from "lucide-react";
import type { Task } from "./types";

export function TaskMemory({
  task,
  busy,
  onSave,
}: {
  task: Task;
  busy: boolean;
  onSave: (text: string, shared: boolean) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [shared, setShared] = useState(false);
  const project = String(task.project_key || "");
  return (
    <article className="settings-card memory-card">
      <h3>
        <BookOpen size={17} />
        任务资料
      </h3>
      <p className="subtle">
        保存已经确认的事实、项目约定和可复用结论。默认只属于当前任务。
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="例如：项目使用 Python 3.11；配置从 config.yaml 读取。"
        disabled={busy}
      />
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={shared && !!project}
          onChange={(e) => setShared(e.target.checked)}
          disabled={!project || busy}
        />
        <span>确认共享到此项目{project ? `「${project}」` : ""}</span>
      </label>
      {!project && (
        <p className="subtle">
          当前任务没有项目标识，资料仅在本任务内使用。新建任务时可以填写项目标识。
        </p>
      )}
      <button
        disabled={busy || !text.trim()}
        onClick={async () => {
          if (await onSave(text.trim(), shared && !!project)) {
            setText("");
            setShared(false);
          }
        }}
      >
        <Save size={15} />
        保存任务资料
      </button>
      <div className="memory-sections">
        <section>
          <h4>本任务资料 · {task.memories?.length || 0}</h4>
          {task.memories?.length ? (
            task.memories.map((item, i) => (
              <div
                className="memory-item"
                key={String(item.memory_id || item.id || i)}
              >
                <p>{String(item.text || item.content || "")}</p>
                <small>
                  {item.share_with_project ? "已确认共享" : "本任务可用"}
                </small>
              </div>
            ))
          ) : (
            <p className="subtle">还没有保存资料。</p>
          )}
        </section>
        <section>
          <h4>
            <ShieldCheck size={14} />
            项目共享经验 · {task.project_memories?.length || 0}
          </h4>
          {task.project_memories?.length ? (
            task.project_memories.map((item, i) => (
              <div
                className="memory-item"
                key={String(item.memory_id || item.id || i)}
              >
                <p>{String(item.text || item.content || "")}</p>
                <small>来自任务 {String(item.task_id || "")}</small>
              </div>
            ))
          ) : (
            <p className="subtle">只有经过确认共享的经验才会出现在这里。</p>
          )}
        </section>
      </div>
    </article>
  );
}
