import { useState } from "react";
import { CalendarClock, Pause } from "lucide-react";
import type { Task } from "./types";

const fullDate = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
export function ScheduleStart({
  task,
  busy,
  onSchedule,
  onCancel,
}: {
  task: Task;
  busy: boolean;
  onSchedule: (runAt: string) => Promise<void>;
  onCancel: () => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const canSchedule =
    ["awaiting_plan_approval", "paused", "blocked"].includes(task.status) &&
    !!task.steps?.length;
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!canSchedule && !task.scheduled_at) return null;
  return (
    <section className="schedule-section">
      <h3>
        <CalendarClock size={17} />
        一次性定时开始
      </h3>
      {task.scheduled_at && (
        <div className={`note ${task.schedule_armed ? "" : "warning"}`}>
          <strong>{task.schedule_armed ? "已安排" : "需要重新安排"}</strong>
          <br />
          {fullDate(task.scheduled_at)}
          <br />
          {task.schedule_armed
            ? `届时执行已批准的 v${task.schedule_plan_version || task.plan_version} 计划。`
            : "此前时间仅作记录；重启后不会自行补跑，请重新选择时间。"}
        </div>
      )}
      {task.schedule_armed && (
        <button
          className="full"
          disabled={busy}
          onClick={() => void onCancel()}
        >
          <Pause size={14} />
          取消安排并保持暂停
        </button>
      )}
      {canSchedule && (
        <>
          <p className="subtle">本次批准在指定时间执行一次，不创建周期任务。</p>
          <label>
            开始时间 · {zone}
            <input
              type="datetime-local"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setError("");
              }}
              disabled={busy}
            />
          </label>
          {error && <p className="field-error">{error}</p>}
          <button
            className="full"
            disabled={busy || !value}
            onClick={() => {
              const when = new Date(value);
              if (
                !Number.isFinite(when.getTime()) ||
                when.getTime() <= Date.now()
              ) {
                setError("请选择一个未来时间。");
                return;
              }
              void onSchedule(when.toISOString());
            }}
          >
            批准该计划并定时开始
          </button>
        </>
      )}
    </section>
  );
}
