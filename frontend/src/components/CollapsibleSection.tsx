import { useState } from "react";
import { ChevronDown } from "lucide-react";

/**
 * Секция со сворачиваемым заголовком. Состояние запоминается в localStorage по
 * `storageKey` (на устройство) — чтобы свёрнутый блок не разворачивался заново
 * при каждом заходе. Типографика заголовка совпадает с обычным SectionTitle.
 */
export function CollapsibleSection({
  title,
  storageKey,
  defaultOpen = true,
  children,
}: {
  title: string;
  storageKey: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(storageKey);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        /* приватный режим / отключённый storage — не критично */
      }
      return next;
    });
  };

  return (
    <section>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="mb-4 flex w-full items-center gap-1.5 text-left"
      >
        <h2
          className="text-[17px] font-semibold leading-tight text-text-primary"
          style={{ letterSpacing: "-0.01em" }}
        >
          {title}
        </h2>
        <ChevronDown
          className={`h-4 w-4 text-text-tertiary transition-transform ${open ? "" : "-rotate-90"}`}
          strokeWidth={2.5}
          aria-hidden
        />
      </button>
      {open && children}
    </section>
  );
}
