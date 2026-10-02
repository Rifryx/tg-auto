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
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
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
