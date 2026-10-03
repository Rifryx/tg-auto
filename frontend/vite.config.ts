import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Все префиксы, которые реально отдаёт backend (api/routers/*.py,
// modules/*/api/router.py). Нужен explicit список, т.к. Vite-прокси
// матчит по точному началу пути.
const API_PREFIXES = [
  "/accounts",
  "/admin",
  "/autopilot",
  "/ban-risk",
  "/billing",
  "/bulk-jobs",
  "/media-assets",
  "/modules",
  "/monitoring",
  "/personas",
  "/profile-assets",
  "/projects",
  "/proxies",
  "/health",
];

// Mini App отдаётся как статика; base относительный, чтобы работать за любым
// префиксом (Telegram открывает по абсолютному URL, но dev/preview проще так).
//
// server.proxy: пробрасывает запросы к backend (localhost:8000) через ЭТОТ
// же dev-сервер (5173). Нужно для single-origin туннелирования (ngrok free
// даёт только один домен) — фронт и API оказываются на одном origin, и
// публично наружу торчит только порт 5173. VITE_API_BASE в этом режиме
// нужно оставить пустым (относительные пути), см. frontend/.env.local.
//
// Vite 5.4+ блокирует запросы с нелокальным Host-заголовком (защита от
// DNS rebinding) — публичный ngrok-домен иначе режется "Blocked request".
// VITE_ALLOWED_HOST=all (или 1/true) → разрешаем все хосты (удобно для
// ngrok с меняющимся поддоменом). Явный хост в VITE_ALLOWED_HOST →
// разрешаем только его.
// Wildcard-синтаксис типа ".ngrok-free.dev" поддерживается только в Vite
// 6+, поэтому в 5.x — только exact match или blanket true.
const allowedHostsEnv = process.env.VITE_ALLOWED_HOST ?? "";
const allowedHosts =
  allowedHostsEnv.toLowerCase() === "all"
    || allowedHostsEnv === "1"
    || allowedHostsEnv.toLowerCase() === "true"
    ? true
    : allowedHostsEnv
      ? allowedHostsEnv.split(",").map((s) => s.trim()).filter(Boolean)
      : undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    ...(allowedHosts !== undefined ? { allowedHosts } : {}),
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [
        p,
        {
          target: process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
          changeOrigin: true,
        },
      ]),
    ),
  },
  build: { target: "es2020", sourcemap: false },
});
