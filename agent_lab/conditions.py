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
    text = _strip_wrapping_parens(text)
    lowered = text.lower()
    if lowered in {"default", "else", "otherwise"}:
        return None
    if lowered in {"true", "yes", "ok", "pass", "passed"}:
        return True
    if lowered in {"false", "no", "fail", "failed"}:
        return False

    for separators, reducer in (
        ((" or ", " || "), any),
        ((" and ", " && "), all),
    ):
        parts = _split_top_level(text, separators)
        if len(parts) > 1:
            values = [evaluate_condition(part, context) for part in parts]
            if any(value is None for value in values):
                return None
            return bool(reducer(bool(value) for value in values))

    if lowered.startswith("not "):
        value = evaluate_condition(text[4:].strip(), context)
        return None if value is None else not value
    if lowered.startswith("!") and not lowered.startswith("!="):
        value = evaluate_condition(text[1:].strip(), context)
        return None if value is None else not value

    function_result = _evaluate_function_condition(text, context)
    if function_result is not None:
        return function_result

    operator_result = _evaluate_text_operator(text, context)
    if operator_result is not None:
        return operator_result

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


def _strip_wrapping_parens(text: str) -> str:
    value = str(text or "").strip()
    while value.startswith("(") and value.endswith(")"):
        inner = value[1:-1].strip()
        if not inner or _find_matching_paren(value, 0) != len(value) - 1:
            break
        value = inner
    return value


def _split_top_level(text: str, separators: tuple[str, ...]) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote and (index == 0 or text[index - 1] != "\\"):
                quote = ""
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")" and depth:
            depth -= 1
            index += 1
            continue
        if depth == 0:
            for separator in separators:
                if text[index : index + len(separator)].lower() == separator:
                    items.append(text[start:index].strip())
                    index += len(separator)
                    start = index
                    break
            else:
                index += 1
            continue
        index += 1
    if not items:
        return [text.strip()]
    items.append(text[start:].strip())
    return [item for item in items if item]


def _find_matching_paren(text: str, start: int) -> int:
    depth = 0
    quote = ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote and text[index - 1] != "\\":
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _evaluate_function_condition(text: str, context: dict[str, Any]) -> bool | None:
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\((.*)\)", text.strip())
    if not match:
        return None
    name = match.group(1).lower()
    args = _split_args(match.group(2))
    if name in {"exists", "present"} and len(args) == 1:
        return resolve_path(context, args[0].strip(), None) is not None
    if name in {"missing", "empty"} and len(args) == 1:
        value = resolve_path(context, args[0].strip(), None)
        if name == "missing":
            return value is None
        return value in (None, "", [], {})
    if name in {"contains", "includes"} and len(args) == 2:
        left = resolve_path(context, args[0].strip(), None)
        right = _parse_literal(args[1].strip(), context)
        return _contains(left, right)
    if name in {"startswith", "starts_with"} and len(args) == 2:
        left = resolve_path(context, args[0].strip(), "")
        right = _parse_literal(args[1].strip(), context)
        return str(left).startswith(str(right))
    if name in {"endswith", "ends_with"} and len(args) == 2:
        left = resolve_path(context, args[0].strip(), "")
        right = _parse_literal(args[1].strip(), context)
        return str(left).endswith(str(right))
    return None


def _evaluate_text_operator(text: str, context: dict[str, Any]) -> bool | None:
    for operator, callback in (
        (" not contains ", lambda left, right: not _contains(left, right)),
        (" contains ", _contains),
        (" includes ", _contains),
        (" startswith ", lambda left, right: str(left).startswith(str(right))),
        (" endswith ", lambda left, right: str(left).endswith(str(right))),
    ):
        index = text.lower().find(operator)
        if index < 0:
            continue
        left_raw = text[:index].strip()
        right_raw = text[index + len(operator) :].strip()
        left = resolve_path(context, left_raw, None)
        if left is None:
            return None
        right = _parse_literal(right_raw, context)
        return bool(callback(left, right))
    return None


def _split_args(raw: str) -> list[str]:
    return _split_top_level(str(raw or ""), (",",))


def _contains(container: Any, needle: Any) -> bool:
    if container is None:
        return False
    if isinstance(container, dict):
        return str(needle) in container or needle in container.values()
    if isinstance(container, (list, tuple, set)):
        return needle in container or str(needle) in {str(item) for item in container}
    return str(needle) in str(container)


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
