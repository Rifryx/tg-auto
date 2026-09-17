import type { Config } from "tailwindcss";

// Цвета — ТОЛЬКО ссылки на CSS-переменные из src/styles/tokens.css (§2 брифа).
// Ни одного hex здесь и в компонентах: единственный источник — tokens.css.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-base": "var(--bg-base)",
        "bg-elevated": "var(--bg-elevated)",
        "surface-1": "var(--surface-1)",
        "surface-2": "var(--surface-2)",
        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-tertiary": "var(--text-tertiary)",
        "status-active": "var(--status-active)",
        "status-warning": "var(--status-warning)",
        "status-critical": "var(--status-critical)",
        "status-neutral": "var(--status-neutral)",
        accent: "var(--accent)",
        "accent-on": "var(--accent-on)",
      },
      borderColor: {
        DEFAULT: "var(--surface-border)",
        hairline: "var(--surface-border)",
        strong: "var(--surface-border-strong)",
      },
      borderRadius: {
        card: "22px",
        chip: "12px",
        pill: "9999px",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "SF Pro",
          "Inter",
          "system-ui",
          "sans-serif",
        ],
      },
      spacing: {
        "safe-b": "env(safe-area-inset-bottom)",
      },
    },
  },
  plugins: [],
} satisfies Config;
