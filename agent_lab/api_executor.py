from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


class CustomApiExecutor:
    """Executor for registered Custom API calls.

    The plugin remains the AstrBot adapter and owns storage plus test hooks. This
    executor owns the API-specific contract: registry lookup, JSON argument
    parsing, credential injection, and HTTP transport.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def call_registered(
        self,
        api_id: str,
        *,
        query_json: str = "",
        body_json: str = "",
        headers_json: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        api_spec = self.owner.storage.get_custom_api(api_id)
        if not api_spec:
            return {}, {}, f"未找到已注册自定义 API：{api_id}"
        if not api_spec.get("url"):
            return {}, api_spec, f"自定义 API {api_id} 未配置 URL。"

        try:
            query = self.parse_json_object(query_json, "query_json")
            headers = self.parse_json_object(headers_json, "headers_json")
            body = self.parse_json_payload(body_json, "body_json")
        except ValueError as exc:
            return {}, api_spec, str(exc)

        headers = {str(k): str(v) for k, v in headers.items()}
        for key, value in (api_spec.get("headers") or {}).items():
            headers.setdefault(str(key), str(value))

        credential_id = str(api_spec.get("credential_id") or "").strip()
        if credential_id:
            secret = self.owner.storage.get_credential_secret(credential_id)
            if not secret:
                api_name = api_spec.get("name") or api_id
                return {}, api_spec, f"自定义 API {api_name} 绑定的凭证为空或无法解密。"
            self.apply_auth(api_spec, headers, query, secret)

        result = await asyncio.to_thread(
            self.owner._perform_custom_api_http_call,
            str(api_spec.get("method") or "GET").upper(),
            str(api_spec.get("url") or ""),
            query,
            body,
            headers,
            int(api_spec.get("timeout_seconds") or 30),
        )
        return result, api_spec, ""

    @staticmethod
    def parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
        raw = str(raw or "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} 不是合法 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{field_name} 必须是 JSON 对象。")
        return payload

    @staticmethod
    def parse_json_payload(raw: str, field_name: str) -> Any:
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} 不是合法 JSON：{exc}") from exc

    @staticmethod
    def apply_auth(
        api_spec: dict[str, Any],
        headers: dict[str, str],
        query: dict[str, Any],
        secret: str,
    ) -> None:
        auth_type = str(api_spec.get("auth_type") or "bearer").strip().lower()
        if auth_type in {"none", "off", "disabled"}:
            return
        if auth_type == "query":
            param = str(api_spec.get("auth_query_param") or "api_key").strip()
            if param:
                query[param] = secret
            return
        header = str(api_spec.get("auth_header") or "Authorization").strip()
        if not header:
            return
        if auth_type == "header":
            headers[header] = secret
        else:
            headers[header] = f"Bearer {secret}"

    @staticmethod
    def perform_http_call(
        method: str,
        url: str,
        query: dict[str, Any],
        body: Any,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        parsed = urlparse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return {
                "ok": False,
                "status": 0,
                "error": "Only http/https custom APIs are supported.",
            }
        existing_query = dict(urlparse.parse_qsl(parsed.query, keep_blank_values=True))
        existing_query.update({str(k): str(v) for k, v in query.items()})
        final_url = urlparse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlparse.urlencode(existing_query),
                parsed.fragment,
            )
        )
        method = method.upper()
        request_body = None
        safe_headers = dict(headers)
        if method not in {"GET", "HEAD"} and body is not None:
            request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            safe_headers.setdefault("Content-Type", "application/json")
        req = urlrequest.Request(
            final_url,
            data=request_body,
            headers=safe_headers,
            method=method,
        )
        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read(256_000)
                text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                return {
                    "ok": 200 <= resp.status < 300,
                    "status": resp.status,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "body": text[:12000],
                    "truncated": len(text) > 12000,
                }
        except urlerror.HTTPError as exc:
            raw = exc.read(64_000)
            text = raw.decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status": exc.code,
                "content_type": exc.headers.get("Content-Type", ""),
                "body": text[:8000],
                "truncated": len(text) > 8000,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
