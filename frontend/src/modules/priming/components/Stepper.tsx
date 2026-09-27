import { Minus, Plus } from "lucide-react";

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
   центр строки, лейбл под ним --text-tertiary 12px. */
export function Stepper({
  label, value, onChange, min = 0, max = 999, step = 1, unit,
}: Props) {
  const set = (v: number) => onChange(Math.max(min, Math.min(max, v)));
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-[22px] font-bold tabular-nums text-text-primary">
          {value}
          {unit && <span className="ml-1 text-[13px] font-medium text-text-tertiary">{unit}</span>}
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
