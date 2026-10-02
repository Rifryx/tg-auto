import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
  /**
   * Акцентная полоса слева:
   * - "primary"   — --accent (ключевой блок мастера);
   * - "secondary" — --status-active (важный, но вторичный);
   * - undefined   — обычная карточка без полосы.
   */
  accent?: "primary" | "secondary";
  /** Иконка в хедере — опционально, рядом с title. */
  icon?: ReactNode;
}

/* Карточка-секция мастера. Гэп между секциями держит родитель. */
export function Section({
  title, description, children, action, accent, icon,
}: Props) {
  const barClass =
    accent === "primary"
      ? "bg-accent"
      : accent === "secondary"
        ? "bg-status-active opacity-80"
        : null;
  return (
    <section className="card relative overflow-hidden p-5">
      {barClass && (
        <span className={`absolute inset-y-0 left-0 w-[3px] ${barClass}`} aria-hidden />
      )}
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {icon}
            <h2 className="text-[17px] font-semibold text-text-primary">{title}</h2>
          </div>
          {description && (
            <p className="mt-1 text-[13px] text-text-secondary">{description}</p>
          )}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
