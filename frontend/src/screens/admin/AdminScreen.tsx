import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Shield } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  adminApi,
  useIsAdmin,
  type AdminPromotion,
  type AdminTimeseriesPoint,
} from "../../shared/admin";
import { STATUS_LABEL } from "../../shared/status";
import type { AccountStatus } from "../../shared/types";
import { hapticSelection } from "../../shared/tg";
import { AreaChart, Bars } from "./charts";

/* Экран владельца. Не пункт меню — попасть только по прямому URL /admin.
   Если сервер вернул не-2xx (не админ) — редиректим на главную. */
export function AdminScreen() {
  const navigate = useNavigate();
  const { isAdmin, isChecking } = useIsAdmin();

  if (isChecking) {
    return <p className="p-6 text-[13px] text-text-tertiary">Проверяем…</p>;
  }
  if (!isAdmin) {
    navigate("/", { replace: true });
    return null;
  }

  return (
    <div className="pb-6 pt-1">
      <header className="mb-6 flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            hapticSelection();
            navigate("/");
          }}
          aria-label="Назад"
          className="inline-flex h-10 w-10 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
        >
          <ArrowLeft className="h-5 w-5" strokeWidth={1.8} aria-hidden />
        </button>
        <Shield className="h-5 w-5 text-text-primary" strokeWidth={1.8} aria-hidden />
        <h1 className="screen-title">Админ</h1>
      </header>

      <AnalyticsSection />
      <ChartsSection />
      <PricingSection />
      <PromotionsSection />
      <SubsSection />
      <SetPlanForm />
    </div>
  );
}

// ------------------------------- аналитика -----------------------------------

function AnalyticsSection() {
  const { data } = useQuery({
    queryKey: ["admin", "analytics"],
    queryFn: adminApi.analytics,
  });
  if (!data) {
    return <p className="mb-6 px-1 text-[13px] text-text-tertiary">Загружаем статистику…</p>;
  }
  const u = data.users;
  const r = data.revenue;
  const a = data.activity;
  const l = data.load;
  return (
    <section className="mb-7">
      <h2 className="mb-4 text-[17px] font-bold text-text-primary">Статистика</h2>

      <Group title="Пользователи">
        <Stat label="Всего" value={u.total} />
        <Stat label="Pro активно" value={u.pro_active} />
        <Stat label="Free" value={u.free} />
        <Stat label="Новых за 7 дн" value={u.new_7d} />
        <Stat label="Истекают ≤7 дн" value={u.expiring_7d} />
        <Stat label="Конверсия" value={`${u.conversion_pct}%`} />
      </Group>

      <Group title="Выручка">
        <Stat label="Оплат всего" value={r.paid_total} />
        <Stat label="Оплат за 30 дн" value={r.paid_30d} />
        <Stat label="В ожидании" value={r.pending} />
      </Group>
      {r.by_currency.length > 0 && (
        <div className="mb-4 card px-4">
          {r.by_currency.map((row, i) => (
            <div
              key={`${row.provider}-${row.currency}`}
              className={`flex items-center justify-between py-2.5 text-[13px] ${
                i > 0 ? "border-t border-hairline" : ""
              }`}
            >
              <span className="text-text-secondary">
                {row.provider} · {row.currency}
              </span>
              <span className="nums font-semibold text-text-primary">
                {row.total.toLocaleString("ru-RU")} ({row.count})
              </span>
            </div>
          ))}
        </div>
      )}

      <Group title="Активность">
        <Stat label="Коммент. 24ч" value={a.comments_24h} />
        <Stat label="Коммент. 7 дн" value={a.comments_7d} />
        <Stat label="Кампании (комм.)" value={a.campaigns.commenting} />
        <Stat label="Кампании (шилл.)" value={a.campaigns.shilling} />
        <Stat label="Кампании (прайм)" value={a.campaigns.priming} />
      </Group>

      <Group title="Нагрузка">
        <Stat label="Аккаунтов всего" value={l.accounts_total} />
        <Stat label="В работе" value={l.accounts_working} />
        <Stat label="Bulk в очереди" value={l.bulk_jobs_queued} />
        <Stat label="Bulk выполняется" value={l.bulk_jobs_running} />
        <Stat label="Персон" value={l.personas} />
        <Stat label="Прокси" value={l.proxies} />
      </Group>
    </section>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="mb-2 px-1 text-[12px] uppercase tracking-wide text-text-tertiary">
        {title}
      </p>
      <div className="card-hero grid grid-cols-3 gap-3 p-4">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: number | string }) {
  return (
    <div>
      <p className="nums text-[20px] font-bold leading-tight text-text-primary">
        {value ?? "—"}
      </p>
      <p className="text-[11px] leading-tight text-text-tertiary">{label}</p>
    </div>
  );
}

// -------------------------------- графики ------------------------------------

const STATUS_TONE: Record<AccountStatus, "active" | "warning" | "critical" | "neutral"> = {
  pool: "active",
  assigned: "active",
  warming: "warning",
  cooldown: "warning",
  banned: "critical",
  created: "neutral",
  retired: "neutral",
};

const BAR_ORDER: AccountStatus[] = [
  "pool",
  "warming",
  "assigned",
  "cooldown",
  "banned",
  "created",
  "retired",
];

function ChartsSection() {
  const { data: ts } = useQuery({
    queryKey: ["admin", "timeseries"],
    queryFn: () => adminApi.timeseries(14),
  });
  const { data: an } = useQuery({
    queryKey: ["admin", "analytics"],
    queryFn: adminApi.analytics,
  });

  if (!ts || !an) {
    return (
      <section className="mb-7">
        <h2 className="mb-4 text-[17px] font-bold text-text-primary">Графики</h2>
        <div className="card h-40 animate-pulse" />
      </section>
    );
  }

  const labels = ts.series.map((p) => p.date);
  const sum = (sel: (p: AdminTimeseriesPoint) => number) =>
    ts.series.reduce((a, p) => a + sel(p), 0);
  const byStatus = an.activity.accounts_by_status ?? {};
  const barItems = BAR_ORDER.map((s) => ({
    label: STATUS_LABEL[s],
    value: byStatus[s] ?? 0,
    tone: STATUS_TONE[s],
  }));

  return (
    <section className="mb-7">
      <h2 className="mb-4 text-[17px] font-bold text-text-primary">
        Графики <span className="text-[13px] font-normal text-text-tertiary">· 14 дней</span>
      </h2>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Новые пользователи" total={sum((p) => p.new_users)}>
          <AreaChart
            data={ts.series.map((p) => p.new_users)}
            labels={labels}
            color="var(--accent)"
          />
        </ChartCard>
        <ChartCard title="Оплаты" total={sum((p) => p.payments)}>
          <AreaChart
            data={ts.series.map((p) => p.payments)}
            labels={labels}
            color="var(--status-active)"
          />
        </ChartCard>
        <ChartCard title="Комментарии" total={sum((p) => p.comments)}>
          <AreaChart
            data={ts.series.map((p) => p.comments)}
            labels={labels}
            color="var(--status-warning)"
          />
        </ChartCard>
        <ChartCard title="Аккаунты по статусам">
          <div className="pt-1">
            <Bars items={barItems} />
          </div>
        </ChartCard>
      </div>
    </section>
  );
}

function ChartCard({
  title,
  total,
  children,
}: {
  title: string;
  total?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <p className="text-[13px] font-semibold text-text-secondary">{title}</p>
        {total !== undefined && (
          <p className="nums text-[18px] font-bold text-text-primary">{total}</p>
        )}
      </div>
      {children}
    </div>
  );
}

// --------------------------------- цена ---------------------------------------

function PricingSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin", "pricing"], queryFn: adminApi.getPricing });
  const [usdt, setUsdt] = useState("");
  const [stars, setStars] = useState("");
  const [days, setDays] = useState("");

  // Префилл при первой загрузке.
  const usdtVal = usdt || (data ? String(data.price_usdt) : "");
  const starsVal = stars || (data ? String(data.price_stars) : "");
  const daysVal = days || (data ? String(data.period_days) : "");

  const mut = useMutation({
    mutationFn: () =>
      adminApi.setPricing({
        price_usdt: usdtVal,
        price_stars: Number(starsVal),
        period_days: Number(daysVal),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "pricing"] });
      qc.invalidateQueries({ queryKey: ["billing", "plan"] });
    },
  });

  return (
    <section className="mb-7">
      <h2 className="mb-4 text-[17px] font-bold text-text-primary">Цена подписки</h2>
      <div className="card flex flex-col gap-3 p-4">
        <Field label="Цена в USDT" value={usdtVal} onChange={setUsdt} mode="decimal" />
        <Field label="Цена в Stars ⭐" value={starsVal} onChange={setStars} mode="numeric" />
        <Field label="Период, дней" value={daysVal} onChange={setDays} mode="numeric" />
        {data?.effective.has_promo && (
          <p className="text-[12px] text-accent">
            Сейчас действует акция: эффективная цена ${data.effective.price_usdt} /{" "}
            {data.effective.price_stars}⭐
          </p>
        )}
        <button
          type="button"
          disabled={mut.isPending}
          onClick={() => mut.mutate()}
          className="mt-1 rounded-pill bg-accent px-4 py-3 text-[14px] font-semibold text-accent-on disabled:opacity-50"
        >
          {mut.isPending ? "Сохраняем…" : "Сохранить цену"}
        </button>
        {mut.isSuccess && <p className="text-[12px] text-status-active">Цена обновлена.</p>}
        {mut.isError && (
          <p className="text-[12px] text-status-critical">
            Не удалось: {(mut.error as Error).message}
          </p>
        )}
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  mode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  mode: "numeric" | "decimal";
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-text-tertiary">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={mode}
        className="nums min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[15px] text-text-primary outline-none focus:border-strong"
      />
    </label>
  );
}

// --------------------------------- акции --------------------------------------

function PromotionsSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin", "promotions"], queryFn: adminApi.listPromotions });
  const [open, setOpen] = useState(false);

  const del = useMutation({
    mutationFn: (id: number) => adminApi.deletePromotion(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "promotions"] });
      qc.invalidateQueries({ queryKey: ["billing", "plan"] });
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      adminApi.patchPromotion(id, { enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "promotions"] });
      qc.invalidateQueries({ queryKey: ["billing", "plan"] });
    },
  });

  return (
    <section className="mb-7">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[17px] font-bold text-text-primary">Акции</h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-pill border border-hairline bg-surface-1 px-3 py-1.5 text-[13px] font-semibold text-text-primary active:bg-surface-2"
        >
          {open ? "Отмена" : "+ Новая"}
        </button>
      </div>

      {open && <NewPromotionForm onDone={() => setOpen(false)} />}

      {data && data.length === 0 && !open && (
        <p className="px-1 text-[13px] text-text-tertiary">Акций пока нет.</p>
      )}
      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((p) => (
            <PromoRow
              key={p.id}
              promo={p}
              onToggle={() => toggle.mutate({ id: p.id, enabled: !p.enabled })}
              onDelete={() => del.mutate(p.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function PromoRow({
  promo,
  onToggle,
  onDelete,
}: {
  promo: AdminPromotion;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const now = Date.now();
  const active =
    promo.enabled &&
    new Date(promo.starts_at).getTime() <= now &&
    new Date(promo.ends_at).getTime() > now;
  const value =
    promo.kind === "percent"
      ? `−${promo.percent_off}%`
      : `$${promo.promo_price_usdt} / ${promo.promo_price_stars}⭐`;
  return (
    <div className="card flex items-center gap-3 p-3.5">
      <span className={`promo-dot promo-dot--${promo.badge_variant}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-semibold text-text-primary">
          {promo.title} · {value}
        </p>
        <p className="text-[11px] text-text-tertiary">
          {new Date(promo.starts_at).toLocaleDateString("ru-RU")} —{" "}
          {new Date(promo.ends_at).toLocaleDateString("ru-RU")}
          {active ? " · активна" : promo.enabled ? " · запланирована" : " · выкл"}
        </p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className="rounded-pill border border-hairline px-2.5 py-1 text-[11px] font-semibold text-text-secondary active:bg-surface-2"
      >
        {promo.enabled ? "Выкл" : "Вкл"}
      </button>
      <button
        type="button"
        onClick={onDelete}
        className="rounded-pill border border-hairline px-2.5 py-1 text-[11px] font-semibold text-status-critical active:bg-surface-2"
      >
        Удалить
      </button>
    </div>
  );
}

function NewPromotionForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"percent" | "fixed">("percent");
  const [percent, setPercent] = useState("50");
  const [priceUsdt, setPriceUsdt] = useState("");
  const [priceStars, setPriceStars] = useState("");
  const [badge, setBadge] = useState<"gold" | "fire" | "neon">("fire");
  const [starts, setStarts] = useState(toLocalInput(new Date()));
  const [ends, setEnds] = useState(toLocalInput(new Date(Date.now() + 7 * 864e5)));

  const mut = useMutation({
    mutationFn: () =>
      adminApi.createPromotion({
        title,
        description: description || null,
        kind,
        percent_off: kind === "percent" ? Number(percent) : null,
        promo_price_usdt: kind === "fixed" ? priceUsdt : null,
        promo_price_stars: kind === "fixed" ? Number(priceStars) : null,
        badge_variant: badge,
        starts_at: new Date(starts).toISOString(),
        ends_at: new Date(ends).toISOString(),
        enabled: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "promotions"] });
      qc.invalidateQueries({ queryKey: ["billing", "plan"] });
      onDone();
    },
  });

  return (
    <div className="mb-3 card flex flex-col gap-3 p-4">
      <Field label="Заголовок" value={title} onChange={setTitle} mode="numeric" />
      <label className="flex flex-col gap-1">
        <span className="text-[12px] text-text-tertiary">Описание (для шторки)</span>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[15px] text-text-primary outline-none focus:border-strong"
        />
      </label>
      <div className="flex gap-2">
        {(["percent", "fixed"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={`flex-1 rounded-pill py-2 text-[13px] font-semibold ${
              kind === k ? "bg-accent text-accent-on" : "border border-hairline bg-surface-1 text-text-secondary"
            }`}
          >
            {k === "percent" ? "Процент" : "Фикс. цена"}
          </button>
        ))}
      </div>
      {kind === "percent" ? (
        <Field label="Скидка, %" value={percent} onChange={setPercent} mode="numeric" />
      ) : (
        <>
          <Field label="Цена USDT" value={priceUsdt} onChange={setPriceUsdt} mode="decimal" />
          <Field label="Цена Stars ⭐" value={priceStars} onChange={setPriceStars} mode="numeric" />
        </>
      )}
      <div className="flex gap-2">
        {(["gold", "fire", "neon"] as const).map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => setBadge(b)}
            className={`flex-1 rounded-pill py-2 text-[12px] font-semibold capitalize ${
              badge === b ? "bg-surface-2 text-text-primary" : "border border-hairline text-text-secondary"
            }`}
          >
            {b}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-[12px] text-text-tertiary">Начало</span>
        <input
          type="datetime-local"
          value={starts}
          onChange={(e) => setStarts(e.target.value)}
          className="min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[14px] text-text-primary outline-none focus:border-strong"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[12px] text-text-tertiary">Конец</span>
        <input
          type="datetime-local"
          value={ends}
          onChange={(e) => setEnds(e.target.value)}
          className="min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[14px] text-text-primary outline-none focus:border-strong"
        />
      </label>
      <button
        type="button"
        disabled={!title.trim() || mut.isPending}
        onClick={() => mut.mutate()}
        className="mt-1 rounded-pill bg-accent px-4 py-3 text-[14px] font-semibold text-accent-on disabled:opacity-50"
      >
        {mut.isPending ? "Создаём…" : "Создать акцию"}
      </button>
      {mut.isError && (
        <p className="text-[12px] text-status-critical">
          Не удалось: {(mut.error as Error).message}
        </p>
      )}
    </div>
  );
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ------------------------------ подписки -------------------------------------

function SubsSection() {
  const { data } = useQuery({
    queryKey: ["admin", "subs"],
    queryFn: adminApi.listSubscriptions,
  });
  return (
    <section className="mb-6">
      <h2 className="mb-4 text-[17px] font-bold text-text-primary">
        Последние подписки
      </h2>
      {data && data.length === 0 && (
        <p className="px-1 text-[13px] text-text-tertiary">Пока никого.</p>
      )}
      {data && data.length > 0 && (
        <div className="card px-4">
          {data.map((s, i) => (
            <div
              key={s.user_id}
              className={`flex items-center justify-between py-3 ${
                i > 0 ? "border-t border-hairline" : ""
              }`}
            >
              <div className="min-w-0">
                <p className="nums truncate text-[14px] text-text-primary">{s.user_id}</p>
                <p className="text-[11px] text-text-tertiary">{s.payment_method ?? "—"}</p>
              </div>
              <span
                className={`nums shrink-0 rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                  s.plan_id === "pro"
                    ? "text-text-primary"
                    : "border border-hairline text-text-secondary"
                }`}
                style={
                  s.plan_id === "pro"
                    ? {
                        background: "var(--surface-2)",
                        boxShadow: "0 0 0 1px var(--surface-border-strong) inset",
                      }
                    : undefined
                }
              >
                {s.plan_id}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SetPlanForm() {
  const qc = useQueryClient();
  const [uid, setUid] = useState("");
  const [plan, setPlan] = useState<"free" | "pro">("pro");
  const [reason, setReason] = useState("");
  const mut = useMutation({
    mutationFn: () => adminApi.setSubscription(uid.trim(), plan, reason || undefined),
    onSuccess: () => {
      setUid("");
      setReason("");
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
  });

  const disabled = !uid.trim() || mut.isPending;

  return (
    <section className="mb-4">
      <h2 className="mb-4 text-[17px] font-bold text-text-primary">
        Выдать/забрать план
      </h2>
      <div className="card flex flex-col gap-3 p-4">
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-text-tertiary">Telegram user_id</span>
          <input
            value={uid}
            onChange={(e) => setUid(e.target.value)}
            inputMode="numeric"
            placeholder="123456789"
            className="nums min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[15px] text-text-primary outline-none focus:border-strong"
          />
        </label>
        <div className="flex gap-2">
          {(["free", "pro"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPlan(p)}
              className={`flex-1 rounded-pill py-2 text-[13px] font-semibold ${
                plan === p
                  ? "bg-accent text-accent-on"
                  : "border border-hairline bg-surface-1 text-text-secondary"
              }`}
            >
              {p.toUpperCase()}
            </button>
          ))}
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-text-tertiary">Причина (опц.)</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="ручная выдача, тест"
            className="min-h-[44px] rounded-chip border border-hairline bg-surface-2 px-3 text-[15px] text-text-primary outline-none focus:border-strong"
          />
        </label>
        <button
          type="button"
          disabled={disabled}
          onClick={() => mut.mutate()}
          className="mt-1 rounded-pill bg-accent px-4 py-3 text-[14px] font-semibold text-accent-on disabled:opacity-50"
        >
          {mut.isPending ? "Сохраняем…" : "Применить"}
        </button>
        {mut.isError && (
          <p className="text-[12px] text-status-critical">
            Не удалось: {(mut.error as Error).message}
          </p>
        )}
        {mut.isSuccess && <p className="text-[12px] text-status-active">Обновлено.</p>}
      </div>
    </section>
  );
}
