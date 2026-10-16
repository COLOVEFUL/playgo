/** REST + WebSocket 客户端；WS 事件通过 bus 广播。 */

import type { WsEvent } from "./types";

export const bus = new EventTarget();

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
    let detail = `${res.status}`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j.detail) detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}
