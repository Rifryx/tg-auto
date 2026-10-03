import { Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";

interface Props {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}

/* Крупный числовой контрол (docs/priming-ui.md §5.5). Число — визуальный
   центр строки, можно либо жать ±, либо ввести значение вручную в
   инлайн-поле. Клэмп делается на blur, чтобы в процессе ввода не
   стирать ведущую цифру. */
export function Stepper({
  label, value, onChange, min = 0, max = 999, step = 1, unit,
}: Props) {
  const [draft, setDraft] = useState<string>(String(value));

  // Внешние изменения (например, applyWarmup) — синхронизируем в draft.
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = (raw: string) => {
    const parsed = parseInt(raw, 10);
    if (Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.max(min, Math.min(max, parsed));
    setDraft(String(clamped));
    if (clamped !== value) onChange(clamped);
  };

  const set = (v: number) => {
    const clamped = Math.max(min, Math.min(max, v));
    setDraft(String(clamped));
    onChange(clamped);
  };

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-baseline gap-1">
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={draft}
            onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.currentTarget.blur();
              }
            }}
            className="w-20 bg-transparent p-0 text-[22px] font-bold tabular-nums text-text-primary outline-none focus:text-accent"
            aria-label={label}
          />
          {unit && (
            <span className="text-[13px] font-medium text-text-tertiary">
              {unit}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[12px] text-text-tertiary">{label}</div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => set(value - step)}
          disabled={value <= min}
          className="flex h-9 w-9 items-center justify-center rounded-pill bg-surface-2 text-text-secondary active:text-text-primary disabled:opacity-40"
          aria-label="Уменьшить"
        >
          <Minus className="h-4 w-4" strokeWidth={2.2} />
        </button>
        <button
          type="button"
          onClick={() => set(value + step)}
          disabled={value >= max}
          className="flex h-9 w-9 items-center justify-center rounded-pill bg-surface-2 text-text-secondary active:text-text-primary disabled:opacity-40"
          aria-label="Увеличить"
        >
          <Plus className="h-4 w-4" strokeWidth={2.2} />
        </button>
      </div>
    </div>
  );
}
