"""Release contract checks. Parses source; does not import/run plugin code."""
import ast
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sources = [root / "main.py", *sorted((root / "agent_lab").glob("*.py"))]
trees = {path: ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)) for path in sources}
main = trees[root / "main.py"]
plugin = next(node for node in main.body if isinstance(node, ast.ClassDef) and node.name == "AgentLabPlugin")
methods = {node.name: node for node in plugin.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
text = (root / "main.py").read_text(encoding="utf-8")
for name in re.findall(r'register_web_api\([^\n]*self\.(api_\w+)', text):
    assert name in methods
    assert any(ast.unparse(decorator) == "admin_api" for decorator in methods[name].decorator_list), name
config = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
assert config["private_only"]["default"] is True
assert 'version: v0.2.5' in (root / "metadata.yaml").read_text(encoding="utf-8")
assert 'PLUGIN_VERSION = "v0.2.5"' in text
assert len(list((root / "modules").glob("*.json"))) == 5
for source in (root / "modules").glob("*.json"):
    json.loads(source.read_text(encoding="utf-8"))
page = root / "pages" / "agent-lab"
assert all((page / name).exists() for name in ["index.html", "app.js", "style.css", "ui-runtime.js", "project-ui.js", "workspace.css", "navigation.js", "theme.css", "vendor/connectors.js"])
js = (page / "app.js").read_text(encoding="utf-8")
assert "sessionStorage." not in js
assert "function taskControlDetail(" in js
assert "function flushWorkflowCanvasDom(" in js
assert "function workflowToolbox(" in js
assert "function subAgentsDrawer(" in js
assert 'refreshWorkflowCanvasDom("view")' in js
project_ui = (page / "project-ui.js").read_text(encoding="utf-8")
workspace_api = (root / "agent_lab" / "workspace_api.py").read_text(encoding="utf-8")
projects = (root / "agent_lab" / "projects.py").read_text(encoding="utf-8")
bridge = (root / "agent_lab" / "astrbot_bridge.py").read_text(encoding="utf-8")
storage = (root / "agent_lab" / "storage.py").read_text(encoding="utf-8")
checks = {
    "administrator_finish_precedes_verifier": text.index('if administrator_override:', text.index('async def _finish_task')) < text.index('self.verifier.verify_finish', text.index('async def _finish_task')),
    "terminal_fence_precedes_wait": projects.index('self.storage.mark_ended(task, status, actor)') < projects.index('task = await self.pause_execution(task)', projects.index('async def administrator_end')),
    "task_history_does_not_switch_daily_conversation": 'manager.new_conversation(' not in bridge and 'manager.switch_conversation(' not in bridge and 'uuid5(NAMESPACE_URL, "agent-lab:"' in bridge,
    "cleanup_is_previewed_and_scoped": 'token != plan["token"]' in projects and 'self.safe_path(path)' in projects and 'delete_conversation(item["umo"], item["cid"])' in projects and 'rmtree' not in projects,
    "daily_summary_bounded": '[:800]' in projects and 'share_with_daily' in projects and 'daily_tools = {' in text,
    "project_summary_bounded": 'limit=3500' in projects and 'project["source_umo"] != task.umo' in projects,
    "late_writes_fenced": 'if self.ended_path(task.task_id).exists():' in storage and 'if not self.owner.storage.ended_path(task.task_id).exists():' in bridge,
    "question_has_explicit_answer": 'def ask(' in (root / "agent_lab" / "task_control.py").read_text(encoding="utf-8") and 'action == "answer"' in workspace_api and 'data-project-action="answer"' in project_ui,
    "embedded_canvas_initial_scale": '|| .72' in js and 'function setMaterialOpen(' in js and 'workflow-panel-resizer' not in js,
    "project_actions_are_authenticated": '@admin_api' in workspace_api and 'self.workspace_api.handle' in text,
}
for name, passed in checks.items():
    assert passed, f"Static contract failed: {name}"
api_actions = set(re.findall(r'this\.request\("([a-z_]+)"', project_ui))
for action in api_actions:
    assert f'"{action}"' in workspace_api, f"Missing project API operation {action}"
print(f"Static review passed: {len(sources)} Python files, API decorators, JSON configuration, original modules and canvas assets.")
print(f"Project contract evidence: {sum(checks.values())}/{len(checks)} source-level assertions passed.")
print("This script checks source only; runtime and browser checks are separate under scripts/ui.")
