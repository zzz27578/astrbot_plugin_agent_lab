import { safeSessionGet, safeSessionSet } from "./storage";

type Bridge = {
  ready?: () => Promise<unknown>;
  apiGet: (
    endpoint: string,
    params?: Record<string, string>,
  ) => Promise<unknown>;
  apiPost: (endpoint: string, body: unknown) => Promise<unknown>;
  subscribeSSE?: (
    endpoint: string,
    handlers: {
      onMessage: (event: unknown) => void;
      onOpen?: () => void;
      onError?: () => void;
    },
    params?: Record<string, string>,
  ) => Promise<string>;
  unsubscribeSSE?: (id: string) => Promise<unknown>;
};
declare global {
  interface Window {
    AstrBotPluginView?: Bridge;
    AstrBotPluginPage?: Bridge;
  }
}
export function bridge(): Bridge | undefined {
  return window.AstrBotPluginView || window.AstrBotPluginPage;
}
export function getToken() {
  // Native plugin views have an opaque origin and authenticate via the parent
  // bridge. Even reading window.sessionStorage there throws SecurityError.
  if (bridge()) return "";
  return (
    new URLSearchParams(location.search).get("token") ||
    safeSessionGet("agent_lab_token") ||
    ""
  );
}
export function saveToken(token: string) {
  if (bridge()) return;
  safeSessionSet("agent_lab_token", token.trim());
  try {
    const url = new URL(location.href);
    url.searchParams.delete("token");
    history.replaceState({}, "", url);
  } catch {
    // Restricted frames may also forbid history changes. Authentication stays
    // available through the in-memory token when browser storage is blocked.
  }
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const current = bridge();
  let value: unknown;
  if (current && typeof current.apiGet === "function") {
    await current.ready?.();
    const url = new URL(path, "https://agent-lab.invalid");
    value =
      body === undefined
        ? await current.apiGet(
            url.pathname.replace(/^\//, ""),
            Object.fromEntries(url.searchParams),
          )
        : await current.apiPost(url.pathname.replace(/^\//, ""), body);
  } else {
    const base =
      document.querySelector<HTMLMetaElement>('meta[name="agent-lab-api-base"]')
        ?.content || "/api";
    const response = await fetch(base.replace(/\/$/, "") + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(getToken() ? { "X-Agent-Lab-Token": getToken() } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    value = await response.json().catch(() => ({
      ok: false,
      error: `接口响应不是 JSON（HTTP ${response.status}）`,
    }));
    if (!response.ok)
      throw new Error(
        (value as { error?: string }).error || `HTTP ${response.status}`,
      );
  }
  const result = value as { ok?: boolean; error?: string; message?: string };
  if (result?.ok === false)
    throw new Error(result.error || result.message || "操作未完成");
  return value as T;
}
export function subscribeEvents(
  onChange: (event: Record<string, unknown>) => void,
  onStatus: (connected: boolean) => void,
): () => void {
  const controller = new AbortController();
  let subscription = "";
  const current = bridge();
  void (async () => {
    try {
      if (current?.subscribeSSE) {
        await current.ready?.();
        subscription = await current.subscribeSSE(
          "harness/events",
          {
            onMessage: (message) => {
              const envelope = message as {
                parsed?: Record<string, unknown>;
                raw?: string;
              };
              try {
                const event =
                  envelope.parsed || JSON.parse(envelope.raw || "{}");
                onChange(event);
              } catch {
                /* A malformed event does not discard the last confirmed state. */
              }
            },
            onOpen: () => onStatus(true),
            onError: () => onStatus(false),
          },
          { after_id: "0" },
        );
        if (controller.signal.aborted)
          await current.unsubscribeSSE?.(subscription);
      } else {
        const base =
          document.querySelector<HTMLMetaElement>(
            'meta[name="agent-lab-api-base"]',
          )?.content || "/api";
        const response = await fetch(
          `${base.replace(/\/$/, "")}/harness/events?after_id=0`,
          {
            headers: getToken() ? { "X-Agent-Lab-Token": getToken() } : {},
            signal: controller.signal,
          },
        );
        if (!response.ok || !response.body)
          throw new Error("Event stream unavailable");
        onStatus(true);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r/g, "");
          let end: number;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const data = event
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (data) {
              try {
                onChange(JSON.parse(data));
              } catch {
                /* Ignore malformed event frames. */
              }
            }
          }
        }
        onStatus(false);
      }
    } catch {
      if (!controller.signal.aborted) onStatus(false);
    }
  })();
  return () => {
    controller.abort();
    if (subscription) void current?.unsubscribeSSE?.(subscription);
  };
}
