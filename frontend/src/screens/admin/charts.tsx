/* Лёгкие inline-SVG графики для админки — без внешних зависимостей, темизируются
   через CSS-переменные токенов. */

interface AreaChartProps {
  data: number[];
  labels: string[];
  color?: string; // CSS-цвет линии/заливки
  height?: number;
}

/* Площадной мини-график тренда: линия + мягкая заливка, точка последнего
   значения, редкие подписи оси X. viewBox фиксирован, ширина — 100%. */
export function AreaChart({
  data,
  labels,
  color = "var(--accent)",
  height = 96,
}: AreaChartProps) {
  const W = 320;
  const H = height;
  const padX = 6;
  const padTop = 10;
  const padBottom = 18;
  const n = data.length;
  const max = Math.max(...data, 1);
  const innerW = W - padX * 2;
  const innerH = H - padTop - padBottom;

  const x = (i: number) => padX + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v: number) => padTop + innerH - (v / max) * innerH;

  const linePts = data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const linePath = `M ${linePts.join(" L ")}`;
  const areaPath =
    `M ${x(0).toFixed(1)},${(padTop + innerH).toFixed(1)} ` +
    `L ${linePts.join(" L ")} ` +
    `L ${x(n - 1).toFixed(1)},${(padTop + innerH).toFixed(1)} Z`;

  const gradId = `g-${Math.random().toString(36).slice(2, 8)}`;
  const last = data[n - 1] ?? 0;
  // Разреженные подписи: первая, средняя, последняя.
  const tickIdx = n > 1 ? [0, Math.floor((n - 1) / 2), n - 1] : [0];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label="График тренда"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={x(n - 1)} cy={y(last)} r="3" fill={color} />
      {tickIdx.map((i) => (
        <text
          key={i}
          x={x(i)}
          y={H - 4}
          textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
          fontSize="9"
          fill="var(--text-tertiary)"
        >
          {shortDate(labels[i])}
        </text>
      ))}
    </svg>
  );
}

function shortDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

interface BarsProps {
  items: { label: string; value: number; tone: "active" | "warning" | "critical" | "neutral" }[];
}

const TONE_VAR: Record<string, string> = {
  active: "var(--status-active)",
  warning: "var(--status-warning)",
  critical: "var(--status-critical)",
  neutral: "var(--status-neutral)",
};

/* Горизонтальные бары — для распределения (аккаунты по статусам). */
export function Bars({ items }: BarsProps) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="flex flex-col gap-2.5">
      {items.map((it) => (
        <div key={it.label} className="flex items-center gap-3">
          <span className="w-20 shrink-0 truncate text-[12px] text-text-secondary">
            {it.label}
          </span>
          <div className="relative h-5 flex-1 overflow-hidden rounded-chip bg-surface-2">
            <div
              className="h-full rounded-chip"
              style={{
                width: `${Math.max((it.value / max) * 100, it.value > 0 ? 6 : 0)}%`,
                background: TONE_VAR[it.tone],
                transition: "width .3s ease",
              }}
            />
          </div>
          <span className="nums w-8 shrink-0 text-right text-[13px] font-semibold text-text-primary">
            {it.value}
          </span>
        </div>
      ))}
    </div>
  );
}
