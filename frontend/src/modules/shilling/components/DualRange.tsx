import { useEffect, useRef, useState } from "react";

/* Диапазонный слайдер с ДВУМЯ ручками («120–480 сек»).
 *
 * Штатный <input type="range"> умеет только одно значение, поэтому кладём два
 * прозрачных инпута друг на друга и рисуем трек сами. Ключевой момент —
 * pointer-events: ручки инпутов кликабельны, а их «полотно» нет, иначе верхний
 * инпут перехватывал бы все клики и нижняя ручка не двигалась бы вовсе.
 *
 * ВАЖНО про плавность. Значение держим в ЛОКАЛЬНОМ state и во время
 * перетаскивания обновляем только его — без сети. ``onChange`` (обычно PATCH
 * на сервер) дёргаем ОДИН раз, на отпускании ручки. Иначе каждый тик слал бы
 * запрос, а ``value`` оставался серверным до ответа — ручка откатывалась на
 * старое место, нативный drag рвался, и слайдер прыгал на один шаг
 * (баг-репорт: «ползунок двигается рывком, не могу зажать и настроить»).
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
  /** Вызывается ОДИН раз на отпускании ручки с итоговым диапазоном. */
  onChange: (lo: number, hi: number) => void;
}) {
  const [draft, setDraft] = useState<[number, number]>([valueMin, valueMax]);
  // Ref с актуальным черновиком: коммит на отпускании читает именно его, а не
  // возможно устаревшее замыкание обработчика.
  const draftRef = useRef<[number, number]>([valueMin, valueMax]);
  // Пока тянем — не даём серверным props перетереть позицию (ответ PATCH,
  // прилетевший посреди жеста, сбил бы ручку).
  const dragging = useRef(false);

  useEffect(() => {
    if (dragging.current) return;
    const pair: [number, number] = [valueMin, valueMax];
    draftRef.current = pair;
    setDraft(pair);
  }, [valueMin, valueMax]);

  const [lo, hi] = draft;
  const span = Math.max(1, max - min);
  const loPct = ((Math.min(lo, hi) - min) / span) * 100;
  const hiPct = ((Math.max(lo, hi) - min) / span) * 100;

  const apply = (pair: [number, number]) => {
    draftRef.current = pair;
    setDraft(pair);
  };
  // Ручки не проскакивают друг сквозь друга: правая не левее левой.
  const setLo = (v: number) => apply([Math.min(v, hi), hi]);
  const setHi = (v: number) => apply([lo, Math.max(v, lo)]);
  const beginDrag = () => {
    dragging.current = true;
  };
  const commit = () => {
    if (!dragging.current) return;
    dragging.current = false;
    const [clo, chi] = draftRef.current;
    if (clo !== valueMin || chi !== valueMax) onChange(clo, chi);
  };

  const handleProps = {
    disabled,
    onMouseDown: beginDrag,
    onTouchStart: beginDrag,
    onKeyDown: beginDrag,
    onMouseUp: commit,
    onTouchEnd: commit,
    onKeyUp: commit,
    onBlur: commit,
    className: "dual-range absolute inset-x-0 top-0 h-5 w-full",
  } as const;

  return (
    <div className={disabled ? "opacity-50" : undefined}>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[13px] text-text-secondary">{label}</span>
        <span className="nums shrink-0 text-[13px] font-semibold text-status-active">
          {lo}–{hi} {unit}
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
          value={lo}
          onChange={(e) => setLo(Number(e.target.value))}
          {...handleProps}
        />
        <input
          type="range"
          aria-label={`${label} — до`}
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => setHi(Number(e.target.value))}
          {...handleProps}
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
