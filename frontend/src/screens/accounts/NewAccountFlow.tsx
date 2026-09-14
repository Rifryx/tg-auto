import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { subscribeStream } from "../../shared/api";
import { haptic } from "../../shared/tg";
import type { LoginState, WarmingProfile } from "../../shared/types";
import { CapsuleButton } from "./components/ui";

type Step = "phone" | "persona" | "waiting" | "code" | "password" | "done";

// text-[16px] важен: меньше iOS зумит поле при фокусе.
const INPUT =
  "w-full min-h-[48px] rounded-chip border border-hairline bg-surface-1 px-4 text-[16px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong";

/* Онбординг аккаунта: шаги отдельными экранами, одно действие в фокусе,
   липкая кнопка снизу (§3/§6 брифа). После создания login_start ставится
   бэкендом автоматически; состояние логина приходит по SSE. */
export function NewAccountFlow() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [proxyId, setProxyId] = useState<number | null>(null);
  const [personaId, setPersonaId] = useState<number | null>(null);
  const [profile] = useState<WarmingProfile>("medium");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const accountIdRef = useRef<number | null>(null);

  const proxies = useQuery({ queryKey: ["proxies"], queryFn: catalogApi.proxies });
  const personas = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });

  const create = useMutation({
    mutationFn: () =>
      accountsApi.create({ phone, proxy_id: proxyId!, persona_id: personaId, warming_profile: profile }),
    onSuccess: (acc) => {
      accountIdRef.current = acc.id;
      // Сразу показываем поле ввода кода: не ждём SSE, чтобы пользователь не
      // застревал на пустом экране, если событие waiting_code задержится.
      setStep("code");
    },
    onError: (e: Error) => setError(e.message),
  });

  // SSE-подписка на состояние логина, пока ждём код / 2FA.
  useEffect(() => {
    const id = accountIdRef.current;
    if (id == null || step === "phone" || step === "persona" || step === "done") return;
    const apply = (state: LoginState | null) => {
      if (state === "waiting_code") setStep((s) => (s === "waiting" || s === "code" ? "code" : s));
      else if (state === "waiting_password") setStep("password");
      else if (state === "success") setStep("done");
      else if (state === "failed") setError("Логин не удался. Попробуйте заново.");
      else if (state === "rate_limited") setError("Слишком часто. Подождите и повторите.");
    };
    accountsApi.loginState(id).then((s) => apply(s.state)).catch(() => {});
    const unsub = subscribeStream(`/accounts/${id}/login/stream`, (data) => {
      const ev = data as { type?: string; account_id?: number; state?: LoginState };
      if (ev.type === "login" && ev.account_id === id) apply(ev.state ?? null);
    });
    return unsub;
  }, [step]);

  const confirmCode = useMutation({
    mutationFn: () => accountsApi.confirmCode(accountIdRef.current!, code),
    onError: (e: Error) => setError(e.message),
  });
  const confirmPassword = useMutation({
    mutationFn: () => accountsApi.confirmPassword(accountIdRef.current!, password),
    onError: (e: Error) => setError(e.message),
  });

  const finish = () =>
    navigate(accountIdRef.current ? `/accounts/${accountIdRef.current}` : "/accounts");

  return (
    <div className="flex min-h-full flex-col pb-28 pt-1">
      <button
        onClick={() => (step === "phone" ? navigate("/accounts") : setStep("phone"))}
        className="inline-flex w-fit items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Назад
      </button>

      {error && (
        <p className="mt-4 rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[13px] text-status-critical">
          {error}
        </p>
      )}

      {step === "phone" && (
        <Stepper title="Новый аккаунт" subtitle="Номер и прокси">
          <Field label="Номер телефона">
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              inputMode="tel"
              placeholder="+380 XX XXX XX XX"
              className={`${INPUT} nums`}
            />
          </Field>
          <Field label="Прокси">
            <select
              value={proxyId ?? ""}
              onChange={(e) => setProxyId(e.target.value ? Number(e.target.value) : null)}
              className={INPUT}
            >
              <option value="">Выберите прокси</option>
              {proxies.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.host}:{p.port} · {p.geo ?? "—"} · {p.status}
                </option>
              ))}
            </select>
          </Field>
        </Stepper>
      )}

      {step === "persona" && (
        <Stepper title="Персона" subtitle="Можно пропустить">
          <div className="flex flex-col gap-2">
            {personas.data?.length ? (
              personas.data.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPersonaId(personaId === p.id ? null : p.id)}
                  className={`card flex items-center justify-between px-4 py-3 text-left ${personaId === p.id ? "border-strong" : ""}`}
                >
                  <span className="text-[15px] text-text-primary">{p.name}</span>
                  {personaId === p.id && (
                    <Check className="h-4 w-4 text-text-primary" strokeWidth={2} aria-hidden />
                  )}
                </button>
              ))
            ) : (
              <p className="text-[13px] text-text-tertiary">Персон пока нет — можно пропустить.</p>
            )}
          </div>
        </Stepper>
      )}

      {step === "code" && (
        <Stepper title="Введите код" subtitle="Telegram отправил код подтверждения">
          <Field label="Код подтверждения">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              autoFocus
              placeholder="12345"
              className={`${INPUT} nums text-[22px] tracking-[0.4em]`}
            />
          </Field>
          <InfoNote>
            Код приходит <b>внутри приложения Telegram</b> (в чат «Telegram»), а не по
            SMS. Не приходит? Проверьте, что номер введён верно и на нём есть активная
            сессия Telegram, подождите до минуты и попробуйте ещё раз.
          </InfoNote>
        </Stepper>
      )}

      {step === "password" && (
        <Stepper title="Пароль 2FA" subtitle="Облачный пароль аккаунта">
          <Field label="Пароль">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              placeholder="••••••••"
              className={INPUT}
            />
          </Field>
        </Stepper>
      )}

      {step === "done" && (
        <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-on">
            <Check className="h-7 w-7" strokeWidth={2.4} aria-hidden />
          </div>
          <p className="text-[17px] font-semibold text-text-primary">Аккаунт подключён</p>
          <p className="mt-1 text-[13px] text-text-secondary">Начался прогрев.</p>
        </div>
      )}

      {/* Липкая кнопка снизу */}
      <StickyBar>
        {step === "phone" && (
          <CapsuleButton
            disabled={!phone.trim() || proxyId == null}
            onClick={() => {
              haptic();
              setStep("persona");
            }}
          >
            Далее
          </CapsuleButton>
        )}
        {step === "persona" && (
          <CapsuleButton disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Создаём…" : "Создать аккаунт"}
          </CapsuleButton>
        )}
        {step === "code" && (
          <CapsuleButton
            disabled={!code.trim() || confirmCode.isPending}
            onClick={() => confirmCode.mutate()}
          >
            {confirmCode.isPending ? "Проверяем…" : "Подтвердить"}
          </CapsuleButton>
        )}
        {step === "password" && (
          <CapsuleButton
            disabled={!password.trim() || confirmPassword.isPending}
            onClick={() => confirmPassword.mutate()}
          >
            {confirmPassword.isPending ? "Проверяем…" : "Войти"}
          </CapsuleButton>
        )}
        {step === "done" && <CapsuleButton onClick={finish}>Открыть аккаунт</CapsuleButton>}
      </StickyBar>
    </div>
  );
}

function Stepper({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4">
      <h1 className="screen-title">{title}</h1>
      <p className="mb-6 mt-1 text-[14px] text-text-secondary">{subtitle}</p>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="mb-4 block">
      <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">{label}</span>
      {children}
    </label>
  );
}

/* Информационная подсказка (что делать, если код не приходит и т.п.). */
function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-1 flex gap-2.5 rounded-chip border border-hairline bg-surface-1 px-4 py-3">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
      <p className="text-[13px] leading-relaxed text-text-secondary">{children}</p>
    </div>
  );
}

function StickyBar({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-30 mx-auto max-w-[440px] border-t border-hairline bg-bg-base px-5 pt-3"
      style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
    >
      {children}
    </div>
  );
}
