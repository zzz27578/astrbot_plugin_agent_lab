"""Derive fixture capabilities from the actual executor registration method."""
import ast
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
registry_type = runpy.run_path(str(ROOT / "agent_lab" / "node_runtime.py"))["NodeExecutorRegistry"]
source = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
method = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "_register_node_executors")
namespace = {}
exec(compile(ast.Module(body=[method], type_ignores=[]), "registration", "exec"), namespace)


class FixtureOwner:
    node_executors = registry_type()

    def __getattr__(self, name):
        if name.startswith("_execute_"):
            return lambda context: None
        raise AttributeError(name)


owner = FixtureOwner()
namespace[method.name](owner)
print(json.dumps(owner.node_executors.catalog()))
