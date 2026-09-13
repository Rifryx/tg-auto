import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { CapsuleButton } from "./ui";
import { AccountPickRow } from "./AccountPickRow";

/* Bottom-sheet выбора аккаунтов из pool (§ треб.): выезжает снизу на
   bg-elevated, закрывается свайпом вниз или тапом вне — не модалка по центру.
   excludeIds — уже привязанные, чтобы не показывать. */
export function AccountPickerSheet({
  open,
  excludeIds,
  onClose,
  onAdd,
  busy,
}: {
  open: boolean;
  excludeIds: number[];
  onClose: () => void;
  onAdd: (accountIds: number[]) => void;
  busy?: boolean;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dragY, setDragY] = useState(0);
  const startY = useRef<number | null>(null);

  const pool = useQuery({
    queryKey: ["accounts", "pool"],
    queryFn: () => accountsApi.list("pool"),
    enabled: open,
  });

  if (!open) return null;

  const available = (pool.data ?? []).filter((a) => !excludeIds.includes(a.id));
  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  const onTouchStart = (e: React.TouchEvent) => (startY.current = e.touches[0].clientY);
  const onTouchMove = (e: React.TouchEvent) => {
    if (startY.current == null) return;
    setDragY(Math.max(0, e.touches[0].clientY - startY.current));
  };
  const onTouchEnd = () => {
    if (dragY > 90) onClose();
    setDragY(0);
    startY.current = null;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onClose}
    >
      <div
        className="mx-auto flex max-h-[80vh] w-full max-w-[440px] flex-col rounded-t-card border-t border-strong bg-bg-elevated"
        style={{ transform: `translateY(${dragY}px)` }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        <div className="flex justify-center pb-2 pt-3">
          <span className="h-1 w-10 rounded-pill bg-surface-2" aria-hidden />
        </div>
        <h3 className="px-5 pb-3 text-[17px] font-semibold text-text-primary">Добавить аккаунты</h3>

        <div className="flex-1 overflow-y-auto px-5">
          {available.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-text-tertiary">
              Нет свободных аккаунтов в пуле.
            </p>
          ) : (
            <div className="flex flex-col gap-2 pb-2">
              {available.map((a) => (
                <AccountPickRow
                  key={a.id}
                  account={a}
                  selected={selected.has(a.id)}
                  onToggle={() => toggle(a.id)}
                />
              ))}
            </div>
          )}
        </div>

        <div
          className="border-t border-hairline px-5 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 14px)" }}
        >
          <CapsuleButton
            disabled={selected.size === 0 || busy}
            variant={selected.size === 0 ? "secondary" : "accent"}
            onClick={() => onAdd([...selected])}
          >
            {busy ? "Добавляем…" : `Добавить (${selected.size})`}
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
