import { ArrowLeft, Check, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { hapticSelection } from "../../shared/tg";
import { useCurrentPlan, useUiStore } from "../../shared/store";
import { PLANS, type Plan } from "../../shared/plans";
import { PaymentSheet } from "./PaymentSheet";

/* Экран выбора тарифа.
   Задача — один смысловой акцент: Pro-карточка тянет взгляд, Free остаётся
   спокойной. Никаких «карточек-близнецов». */
export function BillingScreen() {
  const navigate = useNavigate();
  const current = useCurrentPlan();
  const setPlan = useUiStore((s) => s.setPlan);
  const [payFor, setPayFor] = useState<Plan | null>(null);

  return (
    <div className="min-h-full">
      <header className="mb-8 mt-1 flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            hapticSelection();
            navigate(-1);
          }}
          aria-label="Назад"
          className="inline-flex h-10 w-10 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
        >
          <ArrowLeft className="h-5 w-5" strokeWidth={1.8} aria-hidden />
        </button>
        <h1 className="screen-title">Тарифы</h1>
      </header>

      <p className="mb-8 px-1 text-[14px] leading-relaxed text-text-secondary">
        Free — чтобы попробовать. Pro снимает лимиты и открывает весь функционал,
        включая новые модули по мере их выпуска.
      </p>

      <div className="flex flex-col gap-4">
        {PLANS.map((plan) =>
          plan.id === "pro" ? (
            <ProCard
              key={plan.id}
              plan={plan}
              active={current.id === plan.id}
              onSubscribe={() => {
                hapticSelection();
                setPayFor(plan);
              }}
            />
          ) : (
            <FreeCard
              key={plan.id}
              plan={plan}
              active={current.id === plan.id}
              onSelect={() => {
                hapticSelection();
                setPlan("free");
              }}
            />
          ),
        )}
      </div>

      <p className="mt-6 px-1 text-[11px] leading-relaxed text-text-tertiary">
        Оплата обрабатывается провайдером платежей. Лимиты сбрасываются в начале
        следующего платёжного периода. Отменить подписку можно в любой момент.
      </p>

      {payFor && (
        <PaymentSheet
          plan={payFor}
          onClose={() => setPayFor(null)}
          onPaid={() => {
            setPlan("pro");
            setPayFor(null);
            navigate("/");
          }}
        />
      )}
    </div>
  );
}

/* Free-карточка: тихая, hairline, монохром. */
function FreeCard({
  plan,
  active,
  onSelect,
}: {
  plan: Plan;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <section className="card p-5">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-[18px] font-semibold text-text-primary">{plan.name}</h2>
        <span className="text-[12px] text-text-tertiary">навсегда</span>
      </div>
      <div className="mb-4 nums text-[36px] font-bold leading-none text-text-primary">
        $0
      </div>
      <p className="mb-5 text-[13px] text-text-secondary">{plan.tagline}</p>

      <Bullets items={plan.bullets} tone="muted" />

      <button
        type="button"
        onClick={onSelect}
        disabled={active}
        className={[
          "mt-6 w-full rounded-pill border border-hairline px-4 py-3 text-[14px] font-semibold transition-colors",
          active
            ? "cursor-default bg-surface-2 text-text-secondary"
            : "bg-surface-1 text-text-primary active:bg-surface-2",
        ].join(" ")}
      >
        {active ? "Текущий план" : "Остаться на Free"}
      </button>
    </section>
  );
}

/* Pro-карточка — единственный акцент экрана: индиго-градиент + свечение,
   светящийся hairline, пилюля «Популярный», крупная цена. */
function ProCard({
  plan,
  active,
  onSubscribe,
}: {
  plan: Plan;
  active: boolean;
  onSubscribe: () => void;
}) {
  return (
    <section
      className="relative overflow-hidden rounded-card p-6 text-white"
      style={{
        background:
          "linear-gradient(155deg, #241249 0%, #140a2c 55%, #0b0819 100%)",
        boxShadow:
          "0 0 0 1px rgba(139,92,246,0.45) inset, 0 30px 60px -30px rgba(124,92,255,0.35), 0 0 40px -12px rgba(124,92,255,0.25)",
      }}
    >
        {/* декоративный блик в углу */}
        <div
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full opacity-60"
          style={{
            background:
              "radial-gradient(50% 50% at 50% 50%, rgba(178,145,255,0.35) 0%, rgba(178,145,255,0) 70%)",
          }}
        />

        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-[18px] font-semibold">{plan.name}</h2>
          <span
            className="inline-flex items-center gap-1 rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
            style={{
              background: "rgba(255,255,255,0.12)",
              boxShadow: "0 0 0 1px rgba(255,255,255,0.16) inset",
            }}
          >
            <Sparkles className="h-3 w-3" strokeWidth={2} aria-hidden />
            Популярный
          </span>
        </div>

        <div className="mb-4 flex items-baseline gap-1.5">
          <span className="text-[16px] font-medium opacity-70">$</span>
          <span className="nums text-[48px] font-extrabold leading-none tracking-tight">
            {plan.priceMonth}
          </span>
          <span className="text-[14px] opacity-70">/ мес</span>
        </div>

        <p className="mb-6 text-[13px] opacity-80">{plan.tagline}</p>

        <Bullets items={plan.bullets} tone="bright" />

        <button
          type="button"
          onClick={onSubscribe}
          disabled={active}
          className={[
            "mt-7 w-full rounded-pill px-4 py-3.5 text-[15px] font-semibold transition-transform",
            active
              ? "cursor-default bg-white/15 text-white/70"
              : "bg-white text-[#1a0f45] active:scale-[0.99]",
          ].join(" ")}
          style={
            active
              ? undefined
              : { boxShadow: "0 8px 24px -12px rgba(255,255,255,0.5)" }
          }
        >
          {active ? "Активна" : "Оформить Pro"}
        </button>

        {!active && (
          <div className="mt-3 text-center text-[11px] opacity-70">
            Telegram Stars · Crypto Bot
          </div>
        )}
      </section>
  );
}

function Bullets({
  items,
  tone,
}: {
  items: string[];
  tone: "muted" | "bright";
}) {
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2.5 text-[13.5px] leading-snug">
          <span
            className="mt-[3px] inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full"
            style={
              tone === "bright"
                ? {
                    background:
                      "linear-gradient(135deg, #b291ff 0%, #7c5cff 100%)",
                    boxShadow: "0 0 0 1px rgba(255,255,255,0.15) inset",
                  }
                : {
                    background: "var(--surface-2)",
                    boxShadow: "0 0 0 1px var(--surface-border) inset",
                  }
            }
            aria-hidden
          >
            <Check
              className="h-2.5 w-2.5"
              strokeWidth={3}
              style={{ color: tone === "bright" ? "#1a0f45" : "var(--text-primary)" }}
            />
          </span>
          <span className={tone === "bright" ? "opacity-95" : "text-text-primary"}>
            {t}
          </span>
        </li>
      ))}
    </ul>
  );
}
