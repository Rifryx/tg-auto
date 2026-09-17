import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Shield } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, useIsAdmin } from "../../shared/admin";
import { hapticSelection } from "../../shared/tg";

/* Экран владельца. Не пункт меню — попасть только по прямому URL /admin.
   Если сервер вернул не-2xx (не админ) — редиректим на главную. */
export function AdminScreen() {
  const navigate = useNavigate();
  const { isAdmin, isChecking } = useIsAdmin();

  if (isChecking) {
    return <p className="p-6 text-[13px] text-text-tertiary">Проверяем…</p>;
  }
  if (!isAdmin) {
    // Не рисуем сообщение об ошибке — сразу уходим, как будто маршрута нет.
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

      <StatsSection />
      <SubsSection />
      <SetPlanForm />
    </div>
  );
}

function StatsSection() {
  const { data } = useQuery({ queryKey: ["admin", "stats"], queryFn: adminApi.stats });
  return (
    <section className="mb-6">
      <h2 className="mb-2.5 px-1 text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
        Статистика
      </h2>
      <div className="card grid grid-cols-2 gap-3 p-4">
        <Stat label="Пользователей" value={data?.users} />
        <Stat label="Из них Pro" value={data?.pro_users} />
        <Stat label="Аккаунтов" value={data?.accounts} />
        <Stat label="Кампаний" value={data?.campaigns} />
        <Stat label="Персон" value={data?.personas} />
        <Stat label="Прокси" value={data?.proxies} />
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <div>
      <p className="nums text-[22px] font-bold leading-tight text-text-primary">
        {value ?? "—"}
      </p>
      <p className="text-[12px] text-text-tertiary">{label}</p>
    </div>
  );
}

function SubsSection() {
  const { data } = useQuery({
    queryKey: ["admin", "subs"],
    queryFn: adminApi.listSubscriptions,
  });
  return (
    <section className="mb-6">
      <h2 className="mb-2.5 px-1 text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
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
                <p className="nums truncate text-[14px] text-text-primary">
                  {s.user_id}
                </p>
                <p className="text-[11px] text-text-tertiary">
                  {s.payment_method ?? "—"}
                </p>
              </div>
              <span
                className={`nums shrink-0 rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                  s.plan_id === "pro"
                    ? "text-white"
                    : "border border-hairline text-text-secondary"
                }`}
                style={
                  s.plan_id === "pro"
                    ? {
                        background:
                          "linear-gradient(135deg,#7c5cff 0%,#4b2fbf 100%)",
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
      <h2 className="mb-2.5 px-1 text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
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
        {mut.isSuccess && (
          <p className="text-[12px] text-status-active">Обновлено.</p>
        )}
      </div>
    </section>
  );
}
