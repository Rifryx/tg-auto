/* Диапазонный слайдер с ДВУМЯ ручками («120–480 сек»).
 *
 * Штатный <input type="range"> умеет только одно значение, поэтому кладём два
 * прозрачных инпута друг на друга и рисуем трек сами. Ключевой момент —
 * pointer-events: ручки инпутов кликабельны, а их «полотно» нет, иначе верхний
 * инпут перехватывал бы все клики и нижняя ручка не двигалась бы вовсе.
 */
export function DualRange({
  label,
  hint,
  min,
  max,
  step = 1,
  valueMin,
  valueMax,
  unit = "сек",
  disabled,
  onChange,
  onCommit,
}: {
  label: string;
  hint?: string;
  min: number;
  max: number;
  step?: number;
  valueMin: number;
  valueMax: number;
  unit?: string;
  disabled?: boolean;
  onChange: (lo: number, hi: number) => void;
  onCommit?: () => void;
}) {
  const span = Math.max(1, max - min);
  const loPct = ((Math.min(valueMin, valueMax) - min) / span) * 100;
  const hiPct = ((Math.max(valueMin, valueMax) - min) / span) * 100;

  // Ручки не должны проскакивать друг сквозь друга: правая не левее левой.
  const setLo = (v: number) => onChange(Math.min(v, valueMax), valueMax);
  const setHi = (v: number) => onChange(valueMin, Math.max(v, valueMin));

  return (
    <div className={disabled ? "opacity-50" : undefined}>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[13px] text-text-secondary">{label}</span>
        <span className="nums shrink-0 text-[13px] font-semibold text-status-active">
          {valueMin}–{valueMax} {unit}
        </span>
      </div>

      <div className="relative h-5">
        {/* Трек и заполненный отрезок между ручками. */}
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-pill bg-surface-2" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-pill bg-status-active"
          style={{ left: `${loPct}%`, width: `${Math.max(0, hiPct - loPct)}%` }}
        />
        <input
          type="range"
          aria-label={`${label} — от`}
          min={min}
          max={max}
          step={step}
          value={valueMin}
          disabled={disabled}
          onChange={(e) => setLo(Number(e.target.value))}
          onMouseUp={onCommit}
          onTouchEnd={onCommit}
          onKeyUp={onCommit}
          className="dual-range absolute inset-x-0 top-0 h-5 w-full"
        />
        <input
          type="range"
          aria-label={`${label} — до`}
          min={min}
          max={max}
          step={step}
          value={valueMax}
          disabled={disabled}
          onChange={(e) => setHi(Number(e.target.value))}
          onMouseUp={onCommit}
          onTouchEnd={onCommit}
          onKeyUp={onCommit}
          className="dual-range absolute inset-x-0 top-0 h-5 w-full"
        />
      </div>

      <div className="mt-0.5 flex justify-between text-[11px] text-text-tertiary nums">
        <span>
          {min} {unit}
        </span>
        <span>
          {max} {unit}
        </span>
      </div>
      {hint && <p className="mt-1 text-[11px] leading-snug text-text-tertiary">{hint}</p>}
    </div>
  );
}
