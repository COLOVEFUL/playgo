/** REST + WebSocket 客户端；WS 事件通过 bus 广播。 */

import type { ErrPayload, WsEvent } from "./types";

export const bus = new EventTarget();

/** 后端结构化错误（{code, args}，文案由 i18n.errText 本地化）。 */
export class ApiError extends Error {
  code: string;
  args: Record<string, unknown>;

  constructor(code: string, args: Record<string, unknown>) {
    super(code);
    this.code = code;
    this.args = args;
  }
}

export function onWs(listener: (ev: WsEvent) => void): () => void {
  const h = (e: Event) => listener((e as CustomEvent).detail);
  bus.addEventListener("ws", h);
  return () => bus.removeEventListener("ws", h);
}

let ws: WebSocket | null = null;
let wsTimer: ReturnType<typeof setInterval> | null = null;

export function connectWs(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as WsEvent;
      bus.dispatchEvent(new CustomEvent("ws", { detail: data }));
    } catch {
      /* 忽略非 JSON */
    }
  };
  ws.onclose = () => {
    setTimeout(connectWs, 1500); // 断线重连
  };
  ws.onopen = () => {
    if (wsTimer) clearInterval(wsTimer);
    wsTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
    }, 25000);
  };
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: string | ErrPayload | string[] = `${res.status}`;
    try {
      const j = (await res.json()) as { detail?: string | ErrPayload | string[] };
      if (j.detail) detail = j.detail;
    } catch {
      /* ignore */
    }
    // 结构化错误（{code,args}）→ ApiError；422 校验错误是数组，其余为字符串
    if (typeof detail === "object" && !Array.isArray(detail)) {
      throw new ApiError(detail.code, detail.args ?? {});
    }
    throw new Error(typeof detail === "string" ? detail : `${res.status}`);
  }
  return (await res.json()) as T;
}
