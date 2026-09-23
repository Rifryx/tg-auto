/* Fetch-клиент к backend API (PROJECT-STAGES §6/§10).
 *
 * Авторизация — по Telegram initData. Отправляем сразу три заголовка:
 *  - Authorization: tma <initData>  — стандартная конвенция Telegram Mini App;
 *  - X-Telegram-Init-Data: <initData> — именно его читает наш backend
 *    (api/deps/auth.py::require_user) в проде;
 *  - X-Dev-User: <id> — dev-заглушка бэкенда (DEV_MODE), только в dev.
 * Так фронт совместим и с текущим контрактом бэкенда, и с общей конвенцией. */

import { getDevUserId, getInitData } from "./tg";

const BASE_URL = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  /** Разобранное тело `detail` из FastAPI, если оно объект (напр. 402 limit-exceeded). */
  public detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
  public status: number;
}

function authHeaders(): Record<string, string> {
  const initData = getInitData();
  const headers: Record<string, string> = {};
  if (initData) {
    headers["Authorization"] = `tma ${initData}`;
    headers["X-Telegram-Init-Data"] = initData;
  }
  const devUser = getDevUserId();
  if (devUser) headers["X-Dev-User"] = devUser;
  return headers;
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      // FormData сам выставит multipart-boundary — свой Content-Type не навязываем.
      ...(init.body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...(init.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    let message = res.statusText;
    let detail: unknown = undefined;
    try {
      const body = (await res.json()) as { detail?: unknown; error?: string };
      detail = body.detail ?? body.error;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        // Структурный detail (напр. 402 {reason,feature,limit,...}) — держим
        // читаемый message для логов, а объект — в поле detail.
        message = JSON.stringify(detail);
      }
    } catch {
      /* тело не JSON — оставляем statusText */
    }
    throw new ApiError(res.status, message, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) =>
    apiFetch<T>(path, { method: "POST", body: form }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};

/* SSE поверх fetch + ReadableStream — в отличие от EventSource умеет слать
   заголовки авторизации (initData). Возвращает функцию отписки. */
export function subscribeStream(
  path: string,
  onEvent: (data: unknown) => void,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE_URL}${path}`, {
        headers: { Accept: "text/event-stream", ...authHeaders() },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          try {
            onEvent(JSON.parse(line.slice(5).trim()));
          } catch {
            /* keepalive / не-JSON — пропускаем */
          }
        }
      }
    } catch {
      /* abort или сеть — молча завершаем */
    }
  })();

  return () => controller.abort();
}
