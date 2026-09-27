import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
}

/* Карточка-секция мастера. Гэп между секциями держит родитель
   (24px в PrimingCampaignNew). */
export function Section({ title, description, children, action }: Props) {
  return (
    <section className="card p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[17px] font-semibold text-text-primary">{title}</h2>
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
