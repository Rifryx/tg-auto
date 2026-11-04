import { useEffect, useRef, useState } from "react";

/* Кружок «?» с всплывающим пояснением.
 *
 * Не title-атрибут: на тач-устройствах он не показывается вообще, а у нас
 * половина параметров запуска без объяснения просто непонятна («менять состав
 * между чатами» — что это значит и когда включать?). */
export function HintDot({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex">
      <button
        type="button"
        aria-label="Пояснение"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={[
          "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border text-[11px] leading-none transition-colors",
          open
            ? "border-transparent bg-status-warning/20 text-status-warning"
            : "border-hairline bg-surface-2 text-text-tertiary hover:text-text-secondary",
        ].join(" ")}
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute right-0 top-[22px] z-30 w-60 rounded-chip border border-hairline bg-bg-elevated px-3 py-2 text-[12px] leading-relaxed text-text-secondary shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}
