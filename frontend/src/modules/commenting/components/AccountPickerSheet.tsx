import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, UserPlus, X } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../../shared/accounts";
import { accountDisplay } from "../../../shared/format";
import { AccountAvatar } from "../../../shared/AccountAvatar";
import { accountWorkWarning, sortForWork } from "../../../shared/status";
import { CapsuleButton } from "./ui";
import { AccountPickRow } from "./AccountPickRow";

/* Bottom-sheet выбора аккаунтов из pool (§ треб.): выезжает снизу на
   bg-elevated, закрывается свайпом вниз или тапом вне — не модалка по центру.
   excludeIds — строго скрыть из списка (например, «предварительно отобрано
   на другом шаге»).
   attachedIds — уже в кампании; показываем их отдельной группой сверху как
   неинтерактивные строки «Уже в кампании» и даём кнопку «Убрать», если
   передан onDetach. Так пользователь видит реальное состояние кампании
   прямо в пикере и не ловит невнятную ошибку «already attached». */
export function AccountPickerSheet({
  open,
  excludeIds = [],
  attachedIds = [],
  onClose,
  onAdd,
  onDetach,
  busy,
}: {
  open: boolean;
  excludeIds?: number[];
  attachedIds?: number[];
  onClose: () => void;
  onAdd: (accountIds: number[]) => void;
  onDetach?: (accountId: number) => void;
  busy?: boolean;
}) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dragY, setDragY] = useState(0);
  const startY = useRef<number | null>(null);

  // Показываем аккаунты В ЛЮБОМ статусе (не только пул) — «не идеальные»
  // помечаются предупреждением в строке и общим баннером под списком.
  const pool = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => accountsApi.list(),
    enabled: open,
  });

  if (!open) return null;

  const excludeSet = new Set(excludeIds);
  const attachedSet = new Set(attachedIds);
  const all = pool.data ?? [];
  const attached = sortForWork(
    all.filter((a) => attachedSet.has(a.id) && !excludeSet.has(a.id)),
  );
  const available = sortForWork(
    all.filter((a) => !attachedSet.has(a.id) && !excludeSet.has(a.id)),
  );
  const warnSelected = available.some(
    (a) => selected.has(a.id) && accountWorkWarning(a.status) != null,
  );
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
      className="fixed inset-0 z-50 flex flex-col justify-end bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)] lg:items-center lg:justify-center lg:p-8"
      onClick={onClose}
    >
      <div
        className="mx-auto flex max-h-[80vh] w-full max-w-[440px] flex-col rounded-t-card border-t border-strong bg-bg-elevated lg:max-w-[560px] lg:rounded-card lg:border"
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
          {attached.length === 0 && available.length === 0 ? (
            <div className="flex flex-col items-center gap-4 py-8">
              <p className="text-center text-[13px] text-text-tertiary">
                Нет доступных аккаунтов.
              </p>
              <CapsuleButton onClick={() => navigate("/accounts/new")}>
                <span className="inline-flex items-center gap-1.5">
                  <UserPlus className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                  Зарегистрировать новый аккаунт
                </span>
              </CapsuleButton>
            </div>
          ) : (
            <div className="flex flex-col gap-3 pb-2">
              {attached.length > 0 && (
                <div className="flex flex-col gap-2">
                  <p className="text-[12px] font-semibold text-text-tertiary">
                    Уже в кампании · {attached.length}
                  </p>
                  {attached.map((a) => (
                    <div
                      key={a.id}
                      className="card flex min-h-[56px] w-full items-center gap-3 px-4 py-3 opacity-70"
                    >
                      <AccountAvatar
                        avatarUrl={a.avatar_url}
                        fallback={a.first_name ?? a.username}
                        size={32}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[15px] font-semibold text-text-primary">
                          {accountDisplay(a)}
                        </p>
                        <p className="truncate text-[12px] text-text-tertiary">
                          Уже прикреплён
                        </p>
                      </div>
                      {onDetach ? (
                        <button
                          type="button"
                          onClick={() => onDetach(a.id)}
                          className="inline-flex h-7 items-center gap-1 rounded-pill border border-hairline px-2.5 text-[12px] text-status-critical active:opacity-70"
                        >
                          <X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                          Убрать
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
              {available.length > 0 && (
                <div className="flex flex-col gap-2">
                  {attached.length > 0 && (
                    <p className="text-[12px] font-semibold text-text-tertiary">
                      Можно добавить · {available.length}
                    </p>
                  )}
                  {available.map((a) => (
                    <AccountPickRow
                      key={a.id}
                      account={a}
                      selected={selected.has(a.id)}
                      onToggle={() => toggle(a.id)}
                      note={accountWorkWarning(a.status) ?? undefined}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {warnSelected && (
          <div className="mx-5 mb-1 flex items-start gap-2 rounded-chip border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-[12px] text-status-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
            <span>
              Выбраны не идеальные аккаунты (не из пула): они могут быть не
              прогреты, заняты или на паузе — выше риск бана и ошибок.
            </span>
          </div>
        )}

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
