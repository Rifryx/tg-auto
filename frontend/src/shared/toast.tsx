import { useEffect, useState } from "react";

/* Лёгкий глобальный toast: pub/sub без контекста, чтобы вызывать из любого
   места (в т.ч. из MutationCache.onError в main.tsx). */

export type ToastKind = "error" | "success" | "info";

interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

type Listener = (toasts: ToastItem[]) => void;

let toasts: ToastItem[] = [];
const listeners = new Set<Listener>();
let seq = 0;

function emit() {
  for (const l of listeners) l(toasts);
}

export function showToast(message: string, kind: ToastKind = "info", ttl = 3000): void {
  const id = ++seq;
  toasts = [...toasts, { id, message, kind }];
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, ttl);
}

const KIND_CLS: Record<ToastKind, string> = {
  error: "border-status-critical/40 text-status-critical",
  success: "border-status-active/40 text-status-active",
  info: "border-hairline text-text-primary",
};

/* Контейнер тостов. Монтируется один раз в AppLayout. */
export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>(toasts);
  useEffect(() => {
    listeners.add(setItems);
    return () => {
      listeners.delete(setItems);
    };
  }, []);

  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 px-4">
      {items.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto max-w-[92%] rounded-pill border bg-bg-elevated px-4 py-2 text-[13px] shadow-lg ${KIND_CLS[t.kind]}`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
