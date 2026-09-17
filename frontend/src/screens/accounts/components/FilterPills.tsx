import { hapticSelection } from "../../../shared/tg";
import { ACCOUNT_FILTERS } from "../../../shared/status";
import type { AccountStatus } from "../../../shared/types";

export type AccountFilter = AccountStatus | "all";

/* Пилюли-фильтры (§6 брифа): неактивная — surface-1 + hairline; активная —
   surface-2 + border-strong (НЕ белая заливка — чтобы не спорить с навбаром).
   Горизонтальный скролл при переполнении. */
export function FilterPills({
  value,
  onChange,
}: {
  value: AccountFilter;
  onChange: (v: AccountFilter) => void;
}) {
  return (
    <div className="-mx-5 mb-4 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {ACCOUNT_FILTERS.map((f) => {
        const active = f.value === value;
        return (
          <button
            key={f.value}
            onClick={() => {
              hapticSelection();
              onChange(f.value);
            }}
            className={`min-h-[36px] shrink-0 rounded-pill border px-4 text-[14px] font-medium transition-colors ${
              active
                ? "border-strong bg-surface-2 text-text-primary"
                : "border-hairline bg-surface-1 text-text-secondary"
            }`}
          >
            {f.label}
          </button>
        );
      })}
    </div>
  );
}
