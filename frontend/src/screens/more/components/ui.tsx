import type { LucideIcon } from "lucide-react";
import { ChevronRight } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";

/* Строка списка «Ещё» (паттерн Proton Pass): круглая подложка с иконкой,
   название, шеврон справа. */
export function MoreRow({
  to,
  icon: Icon,
  label,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <Link to={to} className="flex items-center gap-3 px-4 py-3 active:bg-surface-2">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-text-secondary">
        <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden />
      </span>
      <span className="flex-1 text-[15px] text-text-primary">{label}</span>
      <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}

/* Тост снизу экрана (surface-2, не цветной), сам исчезает. */
export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDone, 2500);
    return () => clearTimeout(t);
  }, [message, onDone]);

  if (!message) return null;
  return (
    <div
      className="pointer-events-none fixed inset-x-0 z-50 flex justify-center px-5"
      style={{ bottom: "calc(env(safe-area-inset-bottom) + 104px)" }}
    >
      <div className="rounded-pill border border-hairline bg-surface-2 px-4 py-2.5 text-[14px] text-text-primary">
        {message}
      </div>
    </div>
  );
}
