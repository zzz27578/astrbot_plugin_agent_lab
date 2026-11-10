import { useState } from "react";
import { ClipboardCheck } from "lucide-react";

export function OutcomeReview({
  call,
  busy,
  onSave,
}: {
  call: Record<string, unknown>;
  busy: boolean;
  onSave: (outcome: string, note: string) => Promise<void>;
}) {
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  return (
    <div className="approval">
      <strong>{String(call.tool_name || "工具操作")}</strong>
      <p className="subtle">
        执行已中断，结果还不能确定。请先核对实际文件或外部系统，再记录结论；保存不会自动恢复任务。
      </p>
      <details>
        <summary>查看调用参数与记录</summary>
        <pre>{JSON.stringify(call, null, 2)}</pre>
      </details>
      <label>
        实际结果
        <select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
          disabled={busy}
        >
          <option value="">选择你核实的结果</option>
          <option value="completed">已完成：操作已经生效</option>
          <option value="failed">已失败：确定未成功</option>
          <option value="not_started">未开始：确定没有执行</option>
        </select>
      </label>
      <label>
        核对说明
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
          placeholder="写明检查了什么、发现了什么证据。"
        />
      </label>
      <button
        disabled={busy || !outcome || !note.trim()}
        onClick={() => void onSave(outcome, note.trim())}
      >
        <ClipboardCheck size={14} />
        保存核对结论
      </button>
    </div>
  );
}
