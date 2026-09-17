import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bitcoin, Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { billingApi } from "../../shared/billing";
import { hapticSelection } from "../../shared/tg";
import { PAYMENT_METHODS, type PaymentMethodId, type Plan } from "../../shared/plans";

interface PaymentSheetProps {
  plan: Plan;
  onClose: () => void;
  /* Заглушка успешной оплаты — активируется после подтверждения от провайдера. */
  onPaid: () => void;
}

/* Bottom-sheet выбора способа оплаты для Pro-подписки.
   Пока это витрина: реальные интеграции (createInvoiceLink для Stars,
   createInvoice для CryptoBot) подключаются на бэкенде и триггерят onPaid
   через webhook. Сейчас кнопка «Оплатить» имитирует успех. */
export function PaymentSheet({ plan, onClose, onPaid }: PaymentSheetProps) {
  const [method, setMethod] = useState<PaymentMethodId>("stars");
  const qc = useQueryClient();
  const pay = useMutation({
    // TODO: заменить на реальный createInvoice → провайдер → вебхук ставит план.
    // Пока сразу дёргаем /billing/plan — сервер помечает подписку активной.
    mutationFn: () => billingApi.setPlan(plan.id, method),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["billing", "plan"] });
      onPaid();
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50">
      <div
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="absolute inset-x-0 bottom-0 mx-auto max-w-[440px] rounded-t-[28px] border border-hairline bg-bg-elevated"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-white/15" aria-hidden />

        <div className="flex items-start justify-between px-5 pt-4">
          <div>
            <div className="text-[13px] uppercase tracking-wide text-text-tertiary">
              Оплата
            </div>
            <div className="mt-1 text-[20px] font-bold text-text-primary">
              {plan.name} · ${plan.priceMonth}/мес
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex h-9 w-9 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="mt-5 flex flex-col gap-2 px-4">
          {PAYMENT_METHODS.map((m) => {
            const selected = m.id === method;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => {
                  hapticSelection();
                  setMethod(m.id);
                }}
                className={[
                  "flex items-center gap-3 rounded-card border px-4 py-3.5 text-left transition-colors",
                  selected
                    ? "border-strong bg-surface-2"
                    : "border-hairline bg-surface-1 active:bg-surface-2",
                ].join(" ")}
              >
                <span
                  className="inline-flex h-10 w-10 items-center justify-center rounded-pill"
                  style={{
                    background:
                      m.id === "stars"
                        ? "linear-gradient(135deg,#ffd76a,#ff8a00)"
                        : "linear-gradient(135deg,#4fc3f7,#1976d2)",
                    color: "#1a0f45",
                  }}
                  aria-hidden
                >
                  {m.id === "stars" ? (
                    <Star className="h-5 w-5" strokeWidth={2.2} fill="currentColor" />
                  ) : (
                    <Bitcoin className="h-5 w-5" strokeWidth={2.2} />
                  )}
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="text-[15px] font-semibold text-text-primary">
                    {m.name}
                  </span>
                  <span className="text-[12px] text-text-tertiary">{m.hint}</span>
                </div>
                <span
                  aria-hidden
                  className={[
                    "ml-auto h-5 w-5 rounded-full border-2 transition-colors",
                    selected
                      ? "border-text-primary bg-text-primary"
                      : "border-hairline",
                  ].join(" ")}
                />
              </button>
            );
          })}
        </div>

        {method === "stars" && plan.priceStars && (
          <div className="mt-3 px-5 text-[12px] text-text-tertiary">
            Спишется {plan.priceStars.toLocaleString("ru-RU")} ⭐ (эквивалент $
            {plan.priceMonth}).
          </div>
        )}

        <div className="px-4 pb-2 pt-5">
          <button
            type="button"
            disabled={pay.isPending}
            onClick={() => {
              hapticSelection();
              pay.mutate();
            }}
            className="w-full rounded-pill bg-accent px-4 py-3.5 text-[15px] font-semibold text-accent-on active:opacity-90 disabled:opacity-60"
          >
            {pay.isPending ? "Оплачиваем…" : "Оплатить"}
          </button>
          {pay.isError && (
            <p className="mt-2 px-1 text-center text-[12px] text-status-critical">
              Не удалось активировать подписку. Попробуйте ещё раз.
            </p>
          )}
          <p className="mt-3 px-1 text-center text-[11px] leading-relaxed text-text-tertiary">
            Продолжая, вы соглашаетесь с условиями подписки. Отменить можно
            в любой момент.
          </p>
        </div>
      </div>
    </div>
  );
}
