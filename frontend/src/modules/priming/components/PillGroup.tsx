interface Props<T extends string> {
  value: T;
  options: { key: T; label: string }[];
  onChange: (v: T) => void;
  fullWidth?: boolean;
}

/* Сегмент-контрол на surface-1 с активной пилюлей surface-2 +
   surface-border-strong. НЕ белая заливка — не спорим с FAB'ом
   (см. UI-DESIGN-BRIEF §6). */
export function PillGroup<T extends string>({
  value, options, onChange, fullWidth = false,
}: Props<T>) {
  return (
    <div
      className={[
        "inline-flex gap-1 rounded-pill border border-hairline bg-surface-1 p-1",
        fullWidth ? "w-full" : "",
      ].join(" ")}
    >
      {options.map(({ key, label }) => {
        const active = key === value;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            className={[
              "flex-1 rounded-pill px-3.5 py-1.5 text-[13px] font-medium transition-colors",
              active
                ? "bg-surface-2 text-text-primary border border-strong"
                : "text-text-secondary active:text-text-primary",
            ].join(" ")}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
