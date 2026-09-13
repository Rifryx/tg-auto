import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Mini App отдаётся как статика; base относительный, чтобы работать за любым
// префиксом (Telegram открывает по абсолютному URL, но dev/preview проще так).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  build: { target: "es2020", sourcemap: false },
});
