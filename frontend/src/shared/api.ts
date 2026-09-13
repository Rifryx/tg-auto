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
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
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
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...(init.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string; error?: string };
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* тело не JSON — оставляем statusText */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
