import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Info, Plus, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { subscribeStream } from "../../shared/api";
import { useLimit } from "../../shared/limits";
import { proxiesApi } from "../more/api";
import { Select } from "../../shared/Select";
import { haptic } from "../../shared/tg";
import type { LoginState, Proxy, WarmingProfile } from "../../shared/types";
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
  // Гард против прямого захода на /accounts/new при исчерпанном лимите.
  const limit = useLimit("accounts_max");
  useEffect(() => {
    if (limit?.atLimit) navigate("/billing", { replace: true });
  }, [limit?.atLimit, navigate]);
  const [method, setMethod] = useState<"code" | "session">("code");
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [proxyId, setProxyId] = useState<number | null>(null);
  const [personaId, setPersonaId] = useState<number | null>(null);
  const [profile] = useState<WarmingProfile>("medium");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sessionString, setSessionString] = useState("");
  const [sessionFile, setSessionFile] = useState<File | null>(null);
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

  const importSession = useMutation({
    mutationFn: () =>
      accountsApi.importSession({
        phone: phone.trim(),
        proxy_id: proxyId!,
        warming_profile: profile,
        session_string: sessionString.trim() || undefined,
        session_file: sessionFile ?? undefined,
      }),
    onSuccess: (acc) => {
      accountIdRef.current = acc.id;
      setStep("done");
    },
    onError: (e: Error) => setError(e.message),
  });

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
        <Stepper title="Новый аккаунт" subtitle="Способ подключения">
          <div className="mb-4 flex gap-1 rounded-chip border border-hairline bg-surface-1 p-1">
            {(
              [
                ["code", "По коду"],
                ["session", "Через .session"],
              ] as const
            ).map(([m, label]) => (
              <button
                key={m}
                onClick={() => setMethod(m)}
                className={`min-h-[40px] flex-1 rounded-[9px] text-[14px] font-medium transition-colors ${
                  method === m ? "bg-surface-2 text-text-primary" : "text-text-secondary active:text-text-primary"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
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
            <Select
              value={proxyId != null ? String(proxyId) : ""}
              onChange={(v) => setProxyId(v ? Number(v) : null)}
              placeholder="Выберите прокси"
              options={(proxies.data ?? []).map((p) => ({
                value: String(p.id),
                label: `${p.host}:${p.port} · ${p.geo ?? "—"} · ${p.status}`,
              }))}
            />
          </Field>
          <AutoPickProxyButton
            phone={phone}
            onPicked={(id) => setProxyId(id)}
          />
          <AddProxyInline
            onCreated={(p) => {
              proxies.refetch();
              setProxyId(p.id);
            }}
          />
          {method === "session" && (
            <div className="mt-2">
              <Field label="Файл сессии (.session)">
                <label className="flex min-h-[48px] cursor-pointer items-center gap-2 rounded-chip border border-dashed border-hairline bg-surface-1 px-4 text-[14px] text-text-secondary active:border-strong">
                  <Upload className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
                  <span className="truncate">{sessionFile ? sessionFile.name : "Выбрать .session"}</span>
                  <input
                    type="file"
                    accept=".session,application/octet-stream"
                    onChange={(e) => setSessionFile(e.target.files?.[0] ?? null)}
                    className="hidden"
                  />
                </label>
              </Field>
              <p className="mb-3 px-1 text-[12px] text-text-tertiary">
                Или вставьте StringSession-строку:
              </p>
              <Field label="StringSession (необязательно, если выбран файл)">
                <textarea
                  value={sessionString}
                  onChange={(e) => setSessionString(e.target.value)}
                  placeholder="1BQAN…"
                  rows={3}
                  className={`${INPUT} resize-none py-3 font-mono text-[13px] leading-relaxed`}
                />
              </Field>
              <InfoNote>
                Сессия шифруется перед записью в базу — в открытом виде не хранится.
                .session-файл конвертируется в StringSession на сервере. Аккаунт сразу
                попадёт в пул, код подтверждения не нужен.
              </InfoNote>
            </div>
          )}
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
          <p className="mt-1 text-[13px] text-text-secondary">
            {method === "session" ? "Сессия импортирована, аккаунт в пуле." : "Начался прогрев."}
          </p>
        </div>
      )}

      {/* Липкая кнопка снизу */}
      <StickyBar>
        {step === "phone" && method === "code" && (
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
        {step === "phone" && method === "session" && (
          <CapsuleButton
            disabled={
              !phone.trim() ||
              proxyId == null ||
              (!sessionFile && !sessionString.trim()) ||
              importSession.isPending
            }
            onClick={() => {
              setError(null);
              importSession.mutate();
            }}
          >
            {importSession.isPending ? "Импортируем…" : "Импортировать сессию"}
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

/* Автопик свободного прокси под гео номера (этап 3, backlog #1). */
function AutoPickProxyButton({
  phone,
  onPicked,
}: {
  phone: string;
  onPicked: (id: number) => void;
}) {
  const [status, setStatus] = useState<string | null>(null);
  const pick = useMutation({
    mutationFn: () => proxiesApi.pick({ phone: phone.trim() }),
    onSuccess: (r) => {
      if (r.proxy_id != null) {
        onPicked(r.proxy_id);
        setStatus(
          r.detected_geo
            ? `Подобран под ${r.detected_geo}`
            : "Подобран свободный прокси"
        );
      } else if (r.reason === "no_matching_geo_proxy") {
        setStatus(
          r.detected_geo
            ? `Нет свободного прокси для ${r.detected_geo}`
            : "Нет свободного прокси нужного гео"
        );
      } else {
        setStatus("Свободных прокси нет");
      }
    },
    onError: () => setStatus("Ошибка подбора"),
  });
  const enabled = phone.trim().length >= 4 && !pick.isPending;
  return (
    <div className="mb-3 flex items-center gap-2">
      <button
        onClick={() => enabled && pick.mutate()}
        disabled={!enabled}
        className="rounded-pill border border-hairline bg-surface-2 px-3 py-1.5 text-[13px] text-text-primary disabled:opacity-50"
      >
        {pick.isPending ? "Подбираем…" : "Автоподбор по номеру"}
      </button>
      {status && <p className="text-[12px] text-text-tertiary">{status}</p>}
    </div>
  );
}


/* Инлайн-добавление прокси прямо в онбординге — прокси уходит в общий пул.
   login/password («подписать» прокси) — по желанию, не обязательны. */
function AddProxyInline({ onCreated }: { onCreated: (p: Proxy) => void }) {
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [type, setType] = useState<"socks5" | "http">("socks5");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [geo, setGeo] = useState("");

  const create = useMutation({
    mutationFn: () =>
      catalogApi.createProxy({
        host: host.trim(),
        port: Number(port),
        type,
        login: login.trim() || null,
        password: password.trim() || null,
        geo: geo.trim() || null,
      }),
    onSuccess: (p) => {
      haptic("light");
      setOpen(false);
      setHost(""); setPort(""); setLogin(""); setPassword(""); setGeo("");
      onCreated(p);
    },
  });

  const valid = host.trim() !== "" && Number(port) > 0;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mb-4 inline-flex items-center gap-1.5 px-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <Plus className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Добавить новый прокси
      </button>
    );
  }

  return (
    <div className="mb-4 rounded-card border border-hairline bg-surface-1 p-4">
      <div className="mb-3 flex gap-2">
        <input
          value={host} onChange={(e) => setHost(e.target.value)}
          placeholder="host / IP" className={`${INPUT} flex-1`}
        />
        <input
          value={port} onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))}
          inputMode="numeric" placeholder="port" className={`${INPUT} w-24 nums`}
        />
      </div>
      <div className="mb-3 flex gap-2">
        {(["socks5", "http"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setType(t)}
            className={`min-h-[44px] flex-1 rounded-chip border text-[14px] font-medium ${
              type === t ? "border-strong bg-surface-2 text-text-primary" : "border-hairline text-text-secondary"
            }`}
          >
            {t.toUpperCase()}
          </button>
        ))}
      </div>
      <input value={geo} onChange={(e) => setGeo(e.target.value)} placeholder="Гео (необязательно)" className={`${INPUT} mb-3`} />
      <p className="mb-2 px-1 text-[12px] text-text-tertiary">Авторизация (необязательно)</p>
      <div className="mb-3 flex gap-2">
        <input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="логин" className={`${INPUT} flex-1`} autoComplete="off" />
        <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="пароль" type="password" className={`${INPUT} flex-1`} autoComplete="off" />
      </div>
      {create.isError && (
        <p className="mb-2 text-[13px] text-status-critical">Не удалось добавить прокси.</p>
      )}
      <div className="flex gap-2">
        <CapsuleButton variant="secondary" onClick={() => setOpen(false)}>
          Отмена
        </CapsuleButton>
        <CapsuleButton disabled={!valid || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Добавляем…" : "Добавить в пул"}
        </CapsuleButton>
      </div>
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
