import { useQueryClient } from "@tanstack/react-query";
import { Bitcoin, Star, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { billingApi } from "../../shared/billing";
import { usePricing } from "../../shared/store";
import { hapticSelection, openExternal, openInvoice } from "../../shared/tg";
import { PAYMENT_METHODS, type PaymentMethodId, type Plan } from "../../shared/plans";

interface PaymentSheetProps {
  plan: Plan;
  onClose: () => void;
  /* Вызывается после подтверждённой провайдером оплаты. */
  onPaid: () => void;
}

type Phase = "idle" | "awaiting" | "done" | "error";

const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 150_000;

/* Bottom-sheet оплаты Pro.
   Реальный поток: создаём инвойс на бэкенде → открываем оплату (Stars через
   WebApp.openInvoice, Crypto — внешняя ссылка @CryptoBot) → поллим статус
   платежа до подтверждения. Применение подписки идемпотентно на сервере. */
export function PaymentSheet({ plan, onClose, onPaid }: PaymentSheetProps) {
  const [method, setMethod] = useState<PaymentMethodId>("stars");
  const [phase, setPhase] = useState<Phase>("idle");
  const pricing = usePricing();
  const qc = useQueryClient();
  const pollTimer = useRef<number | null>(null);
  const deadline = useRef<number>(0);

  const stopPolling = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

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
      stopPolling();
    };
  }, [onClose]);

  const settle = async () => {
    await qc.invalidateQueries({ queryKey: ["billing", "plan"] });
    setPhase("done");
    onPaid();
  };

  const pollOnce = async (paymentId: number) => {
    try {
      const res = await billingApi.checkPayment(paymentId);
      if (res.status === "paid" || res.plan === "pro") {
        stopPolling();
        await settle();
        return;
      }
      if (res.status === "expired" || res.status === "failed") {
        stopPolling();
        setPhase("error");
        return;
      }
    } catch {
      /* сеть — продолжаем поллинг до таймаута */
    }
    if (Date.now() >= deadline.current) {
      stopPolling();
      // Таймаут: платёж мог ещё не подтвердиться (крипто-сеть / бот).
      setPhase("error");
      return;
    }
    pollTimer.current = window.setTimeout(() => pollOnce(paymentId), POLL_INTERVAL_MS);
  };

  const startPolling = (paymentId: number) => {
    deadline.current = Date.now() + POLL_TIMEOUT_MS;
    pollTimer.current = window.setTimeout(() => pollOnce(paymentId), POLL_INTERVAL_MS);
  };

  const pay = async () => {
    setPhase("awaiting");
    try {
      const invoice = await billingApi.createInvoice(method);
      if (method === "stars") {
        openInvoice(invoice.url, (status) => {
          if (status === "cancelled" || status === "failed") {
            setPhase("idle");
            return;
          }
          // paid / pending → подтверждение придёт через бота, поллим статус.
          startPolling(invoice.payment_id);
        });
      } else {
        openExternal(invoice.url);
        startPolling(invoice.payment_id);
      }
    } catch {
      setPhase("error");
    }
  };

  const priceUsdt = pricing?.price_usdt ?? plan.priceMonth;
  const priceStars = pricing?.price_stars ?? plan.priceStars ?? 0;
  const hasPromo = pricing?.has_promo ?? false;
  const basePriceUsdt = pricing?.base_price_usdt ?? plan.priceMonth;

  const busy = phase === "awaiting";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center lg:p-8">
      <div onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        className="relative mx-auto w-full max-w-[440px] rounded-t-[28px] border border-hairline bg-bg-elevated pb-[calc(env(safe-area-inset-bottom)+16px)] lg:max-w-[480px] lg:rounded-[28px] lg:pb-4"
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-white/15 lg:hidden" aria-hidden />

        <div className="flex items-start justify-between px-5 pt-4">
          <div>
            <div className="text-[13px] uppercase tracking-wide text-text-tertiary">
              Оплата
            </div>
            <div className="mt-1 flex items-baseline gap-2 text-[20px] font-bold text-text-primary">
              <span>{plan.name} · ${priceUsdt}/мес</span>
              {hasPromo && basePriceUsdt > priceUsdt && (
                <span className="text-[14px] font-medium text-text-tertiary line-through">
                  ${basePriceUsdt}
                </span>
              )}
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

        {hasPromo && (
          <div className="mx-4 mt-3 rounded-card border border-hairline bg-surface-1 px-4 py-2 text-[12px] text-accent">
            🔥 Действует акция — цена снижена
          </div>
        )}

        <div className="mt-4 flex flex-col gap-2 px-4">
          {PAYMENT_METHODS.map((m) => {
            const selected = m.id === method;
            return (
              <button
                key={m.id}
                type="button"
                disabled={busy}
                onClick={() => {
                  hapticSelection();
                  setMethod(m.id);
                }}
                className={[
                  "flex items-center gap-3 rounded-card border px-4 py-3.5 text-left transition-colors disabled:opacity-60",
                  selected
                    ? "border-strong bg-surface-2"
                    : "border-hairline bg-surface-1 active:bg-surface-2",
                ].join(" ")}
              >
                <span
                  className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-surface-2 text-text-secondary"
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
                    selected ? "border-text-primary bg-text-primary" : "border-hairline",
                  ].join(" ")}
                />
              </button>
            );
          })}
        </div>

        {method === "stars" && priceStars > 0 && (
          <div className="mt-3 px-5 text-[12px] text-text-tertiary">
            Спишется {priceStars.toLocaleString("ru-RU")} ⭐ (эквивалент ${priceUsdt}).
          </div>
        )}

        <div className="px-4 pb-2 pt-5">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              hapticSelection();
              void pay();
            }}
            className="w-full rounded-pill bg-accent px-4 py-3.5 text-[15px] font-semibold text-accent-on active:opacity-90 disabled:opacity-60"
          >
            {busy ? "Ожидаем оплату…" : "Оплатить"}
          </button>
          {phase === "awaiting" && (
            <p className="mt-2 px-1 text-center text-[12px] text-text-tertiary">
              Подтвердите оплату в открывшемся окне. Подписка активируется
              автоматически.
            </p>
          )}
          {phase === "error" && (
            <p className="mt-2 px-1 text-center text-[12px] text-status-critical">
              Оплата ещё не подтверждена. Если вы оплатили — подписка активируется
              в течение пары минут.
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
