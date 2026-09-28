import type { HealthDay } from "../types";

/* 40×16 SVG sparkline из трёх наложенных линий (successes / floods /
   privacy) — prompt 7.5. Толщина 1px, цвета — status-tokens. Пустые
   данные рисуются плоской линией внизу, а не скрываются. */

interface Props {
  days: HealthDay[] | undefined;
}

const W = 40;
const H = 16;

export function HealthSparkline({ days }: Props) {
  if (!days || days.length === 0) {
    return <span className="inline-block h-4 w-10 rounded-sm bg-surface-2" />;
  }
  const step = days.length > 1 ? W / (days.length - 1) : 0;
  const maxSuccess = Math.max(1, ...days.map((d) => d.successes));
  const maxIssue = Math.max(
    1,
    ...days.map((d) => Math.max(d.floods, d.privacy)),
  );
  const path = (values: number[], max: number) =>
    "M " +
    values
      .map((v, i) => {
        const x = i * step;
        const y = H - (v / max) * (H - 2) - 1;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" L ");
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-4 w-10"
      preserveAspectRatio="none"
      aria-hidden
    >
      <path
        d={path(days.map((d) => d.successes), maxSuccess)}
        fill="none"
        stroke="var(--status-active)"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d={path(days.map((d) => d.floods), maxIssue)}
        fill="none"
        stroke="var(--status-warning)"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.8"
      />
      <path
        d={path(days.map((d) => d.privacy), maxIssue)}
        fill="none"
        stroke="var(--status-critical)"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.8"
      />
    </svg>
  );
}
