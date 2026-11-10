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
assert 'version: v0.2.3' in (root / "metadata.yaml").read_text(encoding="utf-8")
assert 'PLUGIN_VERSION = "v0.2.3"' in text
assert len(list((root / "modules").glob("*.json"))) == 5
for source in (root / "modules").glob("*.json"):
    json.loads(source.read_text(encoding="utf-8"))
page = root / "pages" / "agent-lab"
assert all((page / name).exists() for name in ["index.html", "app.js", "style.css", "ui-runtime.js"])
js = (page / "app.js").read_text(encoding="utf-8")
assert "sessionStorage." not in js
assert "function taskControlDetail(" in js
assert "function flushWorkflowCanvasDom(" in js
assert "function workflowToolbox(" in js
assert "function subAgentsDrawer(" in js
assert 'refreshWorkflowCanvasDom("view")' in js
print(f"Static review passed: {len(sources)} Python files, API decorators, JSON configuration, original modules and canvas assets.")
print("No AstrBot instance, plugin import, model, tool, or browser was executed.")
