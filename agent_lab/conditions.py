from __future__ import annotations

import re
from typing import Any


_OPS = ("==", "!=", ">=", "<=", ">", "<")


def resolve_path(payload: Any, path: str, default: Any = None) -> Any:
    current = payload
    for raw_part in str(path or "").strip().split("."):
        part = raw_part.strip()
        if not part:
            return default
        if part == "length":
            if isinstance(current, (list, tuple, dict, str)):
                current = len(current)
            else:
                return default
            continue
        if isinstance(current, dict):
            current = current.get(part, default)
            continue
        if isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
            return default
        current = getattr(current, part, default)
    return current


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool | None:
    text = str(expression or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"default", "else", "otherwise"}:
        return None
    if lowered in {"true", "yes", "ok", "pass", "passed"}:
        return True
    if lowered in {"false", "no", "fail", "failed"}:
        return False

    op = next((candidate for candidate in _OPS if candidate in text), "")
    if not op:
        value = resolve_path(context, text)
        if value is None:
            return None
        return bool(value)

    left_raw, right_raw = text.split(op, 1)
    left = resolve_path(context, left_raw.strip())
    right = _parse_literal(right_raw.strip(), context)
    if left is None:
        return None
    try:
        if op == "==":
            return _coerce_scalar(left) == _coerce_scalar(right)
        if op == "!=":
            return _coerce_scalar(left) != _coerce_scalar(right)
        left_num = float(left)
        right_num = float(right)
        if op == ">":
            return left_num > right_num
        if op == "<":
            return left_num < right_num
        if op == ">=":
            return left_num >= right_num
        if op == "<=":
            return left_num <= right_num
    except Exception:
        return None
    return None


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return "any"


def schema_accepts_value(schema: dict[str, Any] | None, value: Any) -> bool:
    return not schema_validation_errors(schema, value)


def schema_validation_errors(
    schema: dict[str, Any] | None,
    value: Any,
    *,
    path: str = "$",
) -> list[str]:
    if not schema:
        return []
    errors: list[str] = []
    expected = schema.get("type")
    if expected and expected != "any":
        accepted = expected if isinstance(expected, list) else [str(expected)]
        actual = value_type(value)
        integer_ok = "integer" in accepted and isinstance(value, int) and not isinstance(value, bool)
        if actual not in accepted and "any" not in accepted and not integer_ok:
            return [f"{path}: expected {expected}, got {actual}"]

    if value_type(value) == "object":
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if str(key) not in value:
                errors.append(f"{path}.{key}: required")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(schema_validation_errors(child_schema, value[key], path=f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: unexpected")

    if value_type(value) == "array" and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value[:50]):
            errors.extend(schema_validation_errors(schema["items"], item, path=f"{path}[{index}]"))
    return errors


def schema_compatible(
    output_schema: dict[str, Any] | None,
    input_schema: dict[str, Any] | None,
) -> bool:
    if not output_schema or not input_schema:
        return True
    out_type = output_schema.get("type") or "any"
    in_type = input_schema.get("type") or "any"
    if out_type == "any" or in_type == "any":
        return True
    if isinstance(in_type, list):
        return out_type in in_type or "any" in in_type
    if isinstance(out_type, list):
        return in_type in out_type or "any" in out_type
    return str(out_type) == str(in_type)


def referenced_paths(expression: str) -> list[str]:
    text = str(expression or "")
    paths: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", text):
        if token not in paths:
            paths.append(token)
    return paths


def _parse_literal(raw: str, context: dict[str, Any]) -> Any:
    text = str(raw or "").strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    try:
        if "." in text:
            return float(text)
        return int(text)
    except Exception:
        value = resolve_path(context, text)
        return text if value is None else value


def _coerce_scalar(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None
    return value
