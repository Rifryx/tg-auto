import { Check } from "lucide-react";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}

/* Квадрат-чекбокс в стиле приложения (парный с modules/parsing).
   При checked — заливка --text-primary, галочка --accent-on. Клик по
   всему ряду, label + description. */

export function Checkbox({
  checked, onChange, label, description, disabled,
}: Props) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex w-full cursor-pointer items-center justify-between gap-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-50"
    >
      <div className="min-w-0">
        <div className="text-[15px] text-text-primary">{label}</div>
        {description && (
          <div className="mt-0.5 text-[12px] text-text-tertiary">
            {description}
          </div>
        )}
      </div>
      <span
        className={[
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors",
          checked
            ? "border-text-primary bg-text-primary"
            : "border-strong bg-surface-1",
        ].join(" ")}
        aria-hidden
      >
        {checked && (
          <Check className="h-3.5 w-3.5 text-accent-on" strokeWidth={2.6} />
        )}
      </span>
    </button>
  );
}
