"""Parse release sources and wire contracts; never import or execute the plugin."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    files = [ROOT / "main.py", ROOT / "__init__.py", *sorted((ROOT / "agent_lab").glob("*.py"))]
    trees = {path: ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)) for path in files}
    config = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert config["disable_group_tasks"]["default"] is True
    assert config["standalone_webui_enabled"]["default"] is False
    metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    entry = (ROOT / "main.py").read_text(encoding="utf-8")
    assert f'version: v{package["version"]}' in metadata
    assert f'PLUGIN_VERSION = "v{package["version"]}"' in entry
    plugin = next(node for node in trees[ROOT / "main.py"].body if isinstance(node, ast.ClassDef) and node.name == "AgentLabPlugin")
    handlers = {node.name for node in plugin.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    routed = set(re.findall(r"\(self\.(api_\w+),\s*\[", entry))
    assert routed <= handlers, "API route references a missing handler"
    standalone = (ROOT / "agent_lab" / "webui_server.py").read_text(encoding="utf-8")
    assert set(re.findall(r"self\.owner\.(api_\w+)", standalone)) <= handlers
    html = (ROOT / "pages" / "agent-lab" / "index.html").read_text(encoding="utf-8")
    assert 'content="/api/plug/astrbot_plugin_agent_lab"' in html
    assets = re.findall(r'(?:src|href)="(\./assets/[^"]+)"', html)
    assert assets, "Production assets were not built"
    for asset in assets:
        assert (ROOT / "pages" / "agent-lab" / asset).is_file(), f"Missing production asset: {asset}"
    # The host iframe intentionally omits allow-same-origin. Keep Storage access
    # behind the guarded helper so initial rendering cannot throw SecurityError.
    frontend_sources = [*sorted((ROOT / "frontend" / "src").glob("*.ts")),
                        *sorted((ROOT / "frontend" / "src").glob("*.tsx"))]
    for source in frontend_sources:
        if source.name == "storage.ts":
            continue
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:sessionStorage|localStorage)\s*(?:\.|\[)", text), (
            f"Use the guarded storage helper in {source.name}"
        )
    ui_entry = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "<StartupBoundary>" in ui_entry, "Rendering errors must remain visible"
    assert 'id="agent-lab-loading"' in html, "Asset loading errors must not leave an empty root"
    forbidden = {"agent_lab_finish", "agent_lab_tick", "agent_lab_request_approval", "agent_lab_call_custom_api"}
    registered_tools = set(re.findall(r'@filter\.llm_tool\(name="([^"]+)"\)', entry))
    assert not (forbidden & registered_tools), "Legacy task mutation tool must not bypass harness controls"
    print(f"Static checks passed: {len(files)} Python sources, JSON/version metadata, {len(routed)} API handlers, {len(assets)} assets, guarded frontend storage.")
    print("No project imports, model calls, runtime tests or browser interaction were performed.")


if __name__ == "__main__":
    main()
