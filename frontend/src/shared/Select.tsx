import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

/* Кастомный дропдаун в стиле мини-аппа (нативный <select> нельзя тематизировать):
   кнопка + всплывающий список на surface-2 с hairline, прокруткой и галочкой у
   выбранного. Закрывается по клику вне и Esc. */
export function Select({
  value,
  onChange,
  options,
  placeholder = "Выберите…",
  disabled,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-[48px] w-full items-center justify-between gap-2 rounded-chip border border-hairline bg-surface-1 px-4 text-left text-[15px] text-text-primary outline-none focus:border-strong disabled:opacity-50"
      >
        <span className={`truncate ${current ? "" : "text-text-tertiary"}`}>
          {current?.label ?? placeholder}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-text-tertiary transition-transform ${open ? "rotate-180" : ""}`}
          strokeWidth={1.8}
          aria-hidden
        />
      </button>

      {open && (
        <div className="absolute left-0 right-0 z-50 mt-1.5 max-h-[280px] overflow-y-auto rounded-card border border-strong bg-surface-2 py-1 shadow-lg [scrollbar-width:thin]">
          {options.length === 0 ? (
            <p className="px-4 py-2 text-[14px] text-text-tertiary">Нет вариантов</p>
          ) : (
            options.map((o) => {
              const active = o.value === value;
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-[15px] active:bg-surface-1 ${
                    active ? "text-text-primary" : "text-text-secondary"
                  }`}
                >
                  <span className="truncate">{o.label}</span>
                  {active && (
                    <Check className="h-4 w-4 shrink-0 text-status-active" strokeWidth={2} aria-hidden />
                  )}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
