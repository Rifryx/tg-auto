import type { ButtonHTMLAttributes, ReactNode } from "react";

/* Капсульная кнопка (§6). При невалидной форме — variant secondary (surface-2),
   не accent. */
type Variant = "accent" | "secondary" | "danger";
const VARIANTS: Record<Variant, string> = {
  accent: "bg-accent text-accent-on",
  secondary: "bg-surface-2 text-text-primary border border-hairline",
  danger: "bg-surface-2 text-status-critical border border-hairline",
};

export function CapsuleButton({
  variant = "accent",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`flex min-h-[48px] w-full items-center justify-center rounded-pill px-5 text-[15px] font-semibold transition-opacity active:opacity-70 disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* Сегмент-контрол (активная — surface-2). */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-chip border border-hairline bg-surface-1 p-1">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`min-h-[40px] flex-1 rounded-[9px] text-[14px] font-medium transition-colors ${
              active ? "bg-surface-2 text-text-primary" : "text-text-secondary active:text-text-primary"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* iOS-переключатель: surface-2 трек, accent когда включён; кружок ездит. */
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-[31px] w-[51px] shrink-0 rounded-pill transition-colors ${
        checked ? "bg-accent" : "bg-surface-2 border border-hairline"
      }`}
    >
      <span
        className={`absolute top-[3px] h-[25px] w-[25px] rounded-full bg-accent-on transition-transform ${
          checked ? "translate-x-[23px]" : "translate-x-[3px]"
        }`}
        style={checked ? undefined : { background: "var(--text-primary)" }}
      />
    </button>
  );
}

export function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mb-7">
      <div className="mb-2.5 flex items-center justify-between px-1">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

const INPUT =
  "w-full min-h-[48px] rounded-chip border border-hairline bg-surface-1 px-4 text-[16px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="mb-4 block">
      <span className="mb-1.5 flex items-center gap-1.5 px-1 text-[13px] text-text-tertiary">
        {label}
        {hint}
      </span>
      {children}
    </label>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${INPUT} ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full min-h-[120px] resize-y rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[15px] leading-relaxed text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong ${props.className ?? ""}`}
    />
  );
}

/* Слайдер задержки: нативный range с accent-color из токена + tabular-nums. */
export function RangeField({
  label,
  value,
  min,
  max,
  onChange,
  onCommit,
  unit = "сек",
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  onCommit?: () => void;
  unit?: string;
}) {
  return (
    <div className="mb-4">
      <div className="mb-1.5 flex items-center justify-between px-1 text-[13px]">
        <span className="text-text-tertiary">{label}</span>
        <span className="nums font-semibold text-text-primary">
          {value} {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={onCommit}
        onTouchEnd={onCommit}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-pill bg-surface-2 [accent-color:var(--accent)]"
      />
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center px-4 pb-8 bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[420px] rounded-card border border-strong bg-bg-elevated p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[18px] font-semibold text-text-primary">{title}</h3>
        <p className="mt-1.5 text-[14px] text-text-secondary">{message}</p>
        <div className="mt-5 flex flex-col gap-2">
          <CapsuleButton variant={danger ? "danger" : "accent"} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </CapsuleButton>
          <CapsuleButton variant="secondary" onClick={onCancel} disabled={busy}>
            Отмена
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
