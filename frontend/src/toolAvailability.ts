export type ToolRow = {
  name: string;
  description?: string;
  enabled?: boolean;
  allowed?: boolean;
};
const core = new Set([
  "astrbot_file_read_tool",
  "astrbot_grep_tool",
  "astrbot_file_write_tool",
  "astrbot_file_edit_tool",
  "astrbot_execute_shell",
  "astrbot_execute_python",
  "astrbot_execute_ipython",
]);
export function toolUnavailable(tool: ToolRow, mode?: string): string {
  if (tool.enabled === false) return "当前未启用";
  if (tool.allowed === false) return "管理员尚未授权";
  if (mode === "sandbox" && tool.name === "astrbot_execute_python")
    return "仅直接模式";
  if (mode === "direct" && tool.name === "astrbot_execute_ipython")
    return "仅沙箱模式";
  if (
    mode === "sandbox" &&
    !core.has(tool.name) &&
    !tool.name.startsWith("api:")
  )
    return "插件工具仅直接模式";
  return "";
}
export function toolModeLabel(name: string) {
  return name === "astrbot_execute_python"
    ? "（直接模式 Python）"
    : name === "astrbot_execute_ipython"
      ? "（沙箱 Python）"
      : name.startsWith("api:")
        ? "（外部 API）"
        : "";
}
