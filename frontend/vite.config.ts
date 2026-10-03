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
// Vite с server.host:true по умолчанию принимает Host только из localhost/
// LAN-адресов (защита от DNS rebinding) — публичный ngrok-домен иначе режется
// ошибкой "Blocked request. This host is not allowed". Разрешаем явно через
// ENV (VITE_ALLOWED_HOST, напр. из frontend/.env.local) + wildcard на все
// *.ngrok-free.app/.dev и *.ngrok.io, чтобы не редактировать конфиг при
// каждом новом случайном поддомене ngrok.
const allowedHosts = [
  ...(process.env.VITE_ALLOWED_HOST ? [process.env.VITE_ALLOWED_HOST] : []),
  ".ngrok-free.app",
  ".ngrok-free.dev",
  ".ngrok.io",
  ".ngrok.app",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    allowedHosts,
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
