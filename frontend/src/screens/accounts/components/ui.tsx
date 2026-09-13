import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { AccountStatus } from "../../../shared/types";
import {
  STATUS_LABEL,
  statusBadgeClass,
  statusDotClass,
} from "../../../shared/status";

/* Точка-индикатор стадии (8px) — §7 брифа. */
export function StatusDot({ status }: { status: AccountStatus }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${statusDotClass(status)}`}
      aria-hidden
    />
  );
}

/* «Мягкий» бейдж стадии (§7): фон = статусный цвет на ~16%, текст — полный. */
export function StatusBadge({ status }: { status: AccountStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-chip px-2.5 py-1 text-[12px] font-semibold ${statusBadgeClass(status)}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/* Капсульная кнопка. variant: accent (белая, §6), secondary (surface-2),
   danger (surface-2 + status-critical текст — деструктив). */
type ButtonVariant = "accent" | "secondary" | "danger";
const VARIANTS: Record<ButtonVariant, string> = {
  accent: "bg-accent text-accent-on",
  secondary: "bg-surface-2 text-text-primary border border-hairline",
  danger: "bg-surface-2 text-status-critical border border-hairline",
};

export function CapsuleButton({
  variant = "accent",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`flex min-h-[48px] w-full items-center justify-center rounded-pill px-5 text-[15px] font-semibold transition-opacity active:opacity-70 disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* Секция карточки-экрана (§4): заголовок + карточка с паддингом. */
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
      <div className="card p-4">{children}</div>
    </section>
  );
}

/* Сегмент-контрол (3 кнопки в ряд, активная — surface-2) — §6/деталь пресета. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  disabled,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex gap-1 rounded-chip border border-hairline bg-surface-1 p-1">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={`min-h-[40px] flex-1 rounded-[9px] text-[14px] font-medium transition-colors disabled:opacity-50 ${
              active
                ? "bg-surface-2 text-text-primary"
                : "text-text-secondary active:text-text-primary"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/* Своя confirm-модалка (НЕ window.confirm) — surface-2 на bg-elevated (§ треб.). */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
  busy,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
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
          <CapsuleButton
            variant={danger ? "danger" : "accent"}
            onClick={onConfirm}
            disabled={busy}
          >
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
