import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Info, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { subscribeStream } from "../../shared/api";
import { useLimit } from "../../shared/limits";
import { proxiesApi } from "../more/api";
import { Select } from "../../shared/Select";
import { haptic } from "../../shared/tg";
import type { LoginState, Proxy, WarmingProfile } from "../../shared/types";
import { CapsuleButton, SegmentedControl } from "./components/ui";

/* Онбординг аккаунта — 4-шаговый мастер с прогресс-баром (§ Этап 0).
   Шаги: 1) Номер+Proxy  2) SMS-код  3) 2FA (если запрошен)  4) Успех.
   Персона задаётся не здесь, а в кампании — так у нас теперь фокус
   регистрации только на "оживить аккаунт". */

type WizardStep = 1 | 2 | 3 | 4;
type Method = "code" | "session";

const STEP_LABELS: Record<WizardStep, string> = {
  1: "Номер телефона",
  2: "SMS код",
  3: "2FA (опционально)",
  4: "Успех",
};

// text-[16px] важен: меньше iOS зумит поле при фокусе.
const INPUT =
  "w-full min-h-[48px] rounded-chip border border-hairline bg-surface-1 px-4 text-[16px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong";

export function NewAccountFlow() {
  const navigate = useNavigate();
  const limit = useLimit("accounts_max");
  useEffect(() => {
    if (limit?.atLimit) navigate("/billing", { replace: true });
  }, [limit?.atLimit, navigate]);

  const [method, setMethod] = useState<Method>("code");
  const [step, setStep] = useState<WizardStep>(1);
  const [phone, setPhone] = useState("");
  const [proxyId, setProxyId] = useState<number | null>(null);
  const [profile] = useState<WarmingProfile>("medium");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sessionString, setSessionString] = useState("");
  const [sessionFile, setSessionFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const accountIdRef = useRef<number | null>(null);

  const proxies = useQuery({ queryKey: ["proxies"], queryFn: catalogApi.proxies });

  const create = useMutation({
    mutationFn: () =>
      accountsApi.create({ phone, proxy_id: proxyId!, persona_id: null, warming_profile: profile }),
    onSuccess: (acc) => {
      accountIdRef.current = acc.id;
      setStep(2);
    },
    onError: (e: Error) => setError(e.message),
  });

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
      setStep(4);
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

  // SSE-подписка на состояние логина: переключаем шаги 2 → 3 → 4 по событиям.
  useEffect(() => {
    const id = accountIdRef.current;
    if (id == null || step === 1) return;
    const apply = (state: LoginState | null) => {
      if (state === "waiting_code") setStep(2);
      else if (state === "waiting_password") setStep(3);
      else if (state === "success") setStep(4);
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

  const back = () => {
    if (step === 1) navigate("/accounts");
    else setStep(((step - 1) as WizardStep) || 1);
  };

  const finish = () =>
    navigate(accountIdRef.current ? `/accounts/${accountIdRef.current}` : "/accounts");

  const startCode = () => {
    setError(null);
    create.mutate();
  };
  const startSession = () => {
    setError(null);
    importSession.mutate();
  };

  return (
    <div className="flex min-h-full flex-col pb-28 pt-1">
      <button
        onClick={back}
        className="inline-flex w-fit items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Назад
      </button>

      <StepProgress current={step} />

      {error && (
        <p className="mt-4 rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[13px] text-status-critical">
          {error}
        </p>
      )}

      {step === 1 && (
        <StepFrame title="Добавить аккаунт" subtitle="Введите номер и настройте прокси">
          <div className="mb-4">
            <SegmentedControl
              value={method}
              onChange={setMethod}
              options={[
                { value: "code", label: "По коду" },
                { value: "session", label: "Через .session" },
              ]}
            />
          </div>

          <PhoneCard phone={phone} onChange={setPhone} />

          <ProxyCard
            proxyId={proxyId}
            proxies={proxies.data ?? []}
            onSelect={setProxyId}
            phone={phone}
            onRefetch={() => proxies.refetch()}
          />

          {method === "session" && (
            <SessionSourceCard
              sessionFile={sessionFile}
              setSessionFile={setSessionFile}
              sessionString={sessionString}
              setSessionString={setSessionString}
            />
          )}
        </StepFrame>
      )}

      {step === 2 && (
        <StepFrame
          title="Введите код"
          subtitle="Telegram отправил код внутри приложения (в чат «Telegram»), не по SMS"
        >
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
            Код приходит <b>в приложении Telegram</b>, а не по SMS. Не пришёл? Проверьте номер,
            подождите до минуты и повторите.
          </InfoNote>
        </StepFrame>
      )}

      {step === 3 && (
        <StepFrame title="Пароль 2FA" subtitle="Облачный пароль от аккаунта Telegram">
          <Field label="Пароль">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              placeholder="••••••••"
              className={INPUT}
            />
          </Field>
        </StepFrame>
      )}

      {step === 4 && (
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

      <StickyBar>
        {step === 1 && method === "code" && (
          <CapsuleButton
            disabled={!phone.trim() || proxyId == null || create.isPending}
            onClick={() => {
              haptic();
              startCode();
            }}
          >
            {create.isPending ? "Отправляем SMS…" : "Отправить SMS код"}
          </CapsuleButton>
        )}
        {step === 1 && method === "session" && (
          <CapsuleButton
            disabled={
              !phone.trim() ||
              proxyId == null ||
              (!sessionFile && !sessionString.trim()) ||
              importSession.isPending
            }
            onClick={startSession}
          >
            {importSession.isPending ? "Импортируем…" : "Импортировать сессию"}
          </CapsuleButton>
        )}
        {step === 2 && (
          <CapsuleButton
            disabled={!code.trim() || confirmCode.isPending}
            onClick={() => confirmCode.mutate()}
          >
            {confirmCode.isPending ? "Проверяем…" : "Подтвердить"}
          </CapsuleButton>
        )}
        {step === 3 && (
          <CapsuleButton
            disabled={!password.trim() || confirmPassword.isPending}
            onClick={() => confirmPassword.mutate()}
          >
            {confirmPassword.isPending ? "Проверяем…" : "Войти"}
          </CapsuleButton>
        )}
        {step === 4 && <CapsuleButton onClick={finish}>Открыть аккаунт</CapsuleButton>}
      </StickyBar>
    </div>
  );
}

/* ── Прогресс-бар шагов (1..4) — верхняя лента как у конкурента (скрин 6). */
function StepProgress({ current }: { current: WizardStep }) {
  const steps: WizardStep[] = [1, 2, 3, 4];
  return (
    <div className="mt-4 mb-4 flex items-center gap-2">
      {steps.map((s, i) => {
        const active = s === current;
        const done = s < current;
        return (
          <div key={s} className="flex flex-1 items-center gap-2">
            <div
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${
                done
                  ? "bg-accent text-accent-on"
                  : active
                  ? "border border-strong bg-surface-2 text-text-primary"
                  : "border border-hairline bg-surface-1 text-text-tertiary"
              }`}
            >
              {done ? <Check className="h-3.5 w-3.5" strokeWidth={2.4} aria-hidden /> : s}
            </div>
            {i < steps.length - 1 && (
              <div
                className={`h-px flex-1 ${done ? "bg-accent" : "bg-hairline"}`}
                aria-hidden
              />
            )}
          </div>
        );
      })}
      <span className="ml-2 shrink-0 text-[12px] text-text-tertiary">
        {STEP_LABELS[current]}
      </span>
    </div>
  );
}

function StepFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-2">
      <h1 className="screen-title">{title}</h1>
      <p className="mb-6 mt-1 text-[14px] text-text-secondary">{subtitle}</p>
      {children}
    </div>
  );
}

/* ── Карточка «Номер телефона» — согласована с UI конкурента (скрин 6). */
function PhoneCard({ phone, onChange }: { phone: string; onChange: (v: string) => void }) {
  return (
    <div className="mb-4 rounded-card border border-hairline bg-surface-1 p-4">
      <p className="mb-2 text-[13px] font-semibold text-text-primary">Введите номер телефона</p>
      <p className="mb-3 text-[12px] text-text-tertiary">
        Номер Telegram с кодом страны (например, +380123456789 или 380123456789)
      </p>
      <Field label="Номер телефона">
        <input
          value={phone}
          onChange={(e) => onChange(e.target.value)}
          inputMode="tel"
          placeholder="+380123456789 или 380123456789"
          className={`${INPUT} nums`}
        />
      </Field>
      <p className="px-1 text-[12px] text-text-tertiary">
        Префикс + опциональный, он будет добавлен автоматически
      </p>
    </div>
  );
}

/* ── Карточка «Прокси» — таб «Строковый / Детальный формат» + автопик +
   выбор из существующего пула (свёрнут в аккордеон). */
function ProxyCard({
  proxyId,
  proxies,
  onSelect,
  phone,
  onRefetch,
}: {
  proxyId: number | null;
  proxies: Proxy[];
  onSelect: (id: number | null) => void;
  phone: string;
  onRefetch: () => void;
}) {
  const [mode, setMode] = useState<"string" | "detail">("string");
  const [showPool, setShowPool] = useState(false);
  const selected = useMemo(
    () => proxies.find((p) => p.id === proxyId) ?? null,
    [proxies, proxyId]
  );

  return (
    <div className="mb-4 rounded-card border border-strong bg-surface-1 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-semibold text-text-primary">Настройки прокси</p>
          <p className="text-[12px] text-text-tertiary">Обязательно</p>
        </div>
        <span className="rounded-chip bg-status-critical/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-status-critical">
          Обязательно
        </span>
      </div>

      <div className="mb-4">
        <SegmentedControl
          value={mode}
          onChange={setMode}
          options={[
            { value: "string", label: "Строковый формат" },
            { value: "detail", label: "Детальная форма" },
          ]}
        />
      </div>

      {mode === "string" ? (
        <ProxyStringForm onCreated={(p) => { onRefetch(); onSelect(p.id); }} />
      ) : (
        <ProxyDetailForm onCreated={(p) => { onRefetch(); onSelect(p.id); }} />
      )}

      <div className="mt-4 border-t border-hairline pt-3">
        <AutoPickProxyButton phone={phone} onPicked={onSelect} />
        <button
          onClick={() => setShowPool((v) => !v)}
          className="text-[13px] text-text-secondary active:text-text-primary"
        >
          {showPool ? "Скрыть пул" : "Или выбрать из существующего пула"}
        </button>
        {showPool && (
          <div className="mt-3">
            <Select
              value={proxyId != null ? String(proxyId) : ""}
              onChange={(v) => onSelect(v ? Number(v) : null)}
              placeholder="Выберите прокси"
              options={proxies.map((p) => ({
                value: String(p.id),
                label: `${p.host}:${p.port} · ${p.geo ?? "—"} · ${p.status}`,
              }))}
            />
          </div>
        )}
        {selected && (
          <p className="mt-2 text-[12px] text-text-tertiary">
            Выбран: <span className="text-text-primary">{selected.host}:{selected.port}</span> ·{" "}
            {selected.geo ?? "гео —"} · {selected.type}
          </p>
        )}
      </div>
    </div>
  );
}

/* Парсер строки socks5://user:pass@host:port или socks5://host:port. */
function parseProxyString(raw: string): {
  type: "socks5" | "http";
  host: string;
  port: number;
  login: string | null;
  password: string | null;
} | null {
  try {
    // URL требует протокол; наши варианты — socks5:// и http://.
    const norm = raw.trim();
    if (!/^(socks5|http):\/\//i.test(norm)) return null;
    const u = new URL(norm.replace(/^socks5:/i, "http:"));
    const type = /^socks5:/i.test(norm) ? "socks5" : "http";
    const port = Number(u.port);
    if (!u.hostname || !port) return null;
    return {
      type,
      host: u.hostname,
      port,
      login: u.username ? decodeURIComponent(u.username) : null,
      password: u.password ? decodeURIComponent(u.password) : null,
    };
  } catch {
    return null;
  }
}

function ProxyStringForm({ onCreated }: { onCreated: (p: Proxy) => void }) {
  const [value, setValue] = useState("");
  const parsed = useMemo(() => parseProxyString(value), [value]);
  const create = useMutation({
    mutationFn: () => {
      if (!parsed) throw new Error("Некорректная строка прокси");
      return catalogApi.createProxy({
        host: parsed.host,
        port: parsed.port,
        type: parsed.type,
        login: parsed.login,
        password: parsed.password,
        geo: null,
      });
    },
    onSuccess: (p) => {
      haptic("light");
      setValue("");
      onCreated(p);
    },
  });

  return (
    <div>
      <Field label="Строка прокси">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="socks5://user:pass@host:port или socks5://host:port"
          className={`${INPUT} font-mono text-[13px]`}
          autoComplete="off"
        />
      </Field>
      <p className="mb-3 px-1 text-[12px] text-text-tertiary">
        Примеры: socks5://127.0.0.1:1080 или socks5://user:pass@proxy.com:1080
      </p>
      {value && !parsed && (
        <p className="mb-3 px-1 text-[12px] text-status-critical">Строка не распознана.</p>
      )}
      {parsed && (
        <p className="mb-3 px-1 text-[12px] text-text-tertiary">
          <span className="text-text-primary">{parsed.type.toUpperCase()}</span> · {parsed.host}:{parsed.port}
          {parsed.login ? ` · auth: ${parsed.login}` : ""}
        </p>
      )}
      <CapsuleButton
        variant="secondary"
        disabled={!parsed || create.isPending}
        onClick={() => create.mutate()}
      >
        {create.isPending ? "Добавляем…" : "Добавить и выбрать"}
      </CapsuleButton>
      {create.isError && (
        <p className="mt-2 px-1 text-[12px] text-status-critical">Не удалось добавить прокси.</p>
      )}
    </div>
  );
}

function ProxyDetailForm({ onCreated }: { onCreated: (p: Proxy) => void }) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("1080");
  const [type, setType] = useState<"socks5" | "http">("socks5");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);

  const create = useMutation({
    mutationFn: () =>
      catalogApi.createProxy({
        host: host.trim(),
        port: Number(port),
        type,
        login: login.trim() || null,
        password: password.trim() || null,
        geo: null,
      }),
    onSuccess: (p) => {
      haptic("light");
      setHost(""); setPort("1080"); setLogin(""); setPassword("");
      onCreated(p);
    },
  });

  const valid = host.trim() !== "" && Number(port) > 0;

  return (
    <div>
      <div className="mb-3 grid grid-cols-[110px_1fr_110px] gap-2">
        <div>
          <p className="mb-1.5 px-1 text-[12px] text-text-tertiary">Тип</p>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as "socks5" | "http")}
            className={INPUT}
          >
            <option value="socks5">socks5</option>
            <option value="http">http</option>
          </select>
        </div>
        <div>
          <p className="mb-1.5 px-1 text-[12px] text-text-tertiary">Хост</p>
          <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="proxy.example.com" className={INPUT} />
        </div>
        <div>
          <p className="mb-1.5 px-1 text-[12px] text-text-tertiary">Порт</p>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))}
            inputMode="numeric"
            className={`${INPUT} nums`}
          />
        </div>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2">
        <div>
          <p className="mb-1.5 px-1 text-[12px] text-text-tertiary">
            Имя пользователя (опционально)
          </p>
          <input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="username" className={INPUT} autoComplete="off" />
        </div>
        <div>
          <p className="mb-1.5 px-1 text-[12px] text-text-tertiary">Пароль (опционально)</p>
          <div className="relative">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type={showPass ? "text" : "password"}
              placeholder="password"
              className={`${INPUT} pr-10`}
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowPass((v) => !v)}
              aria-label={showPass ? "Скрыть" : "Показать"}
              className="absolute inset-y-0 right-2 px-2 text-[12px] text-text-tertiary"
            >
              {showPass ? "скрыть" : "показать"}
            </button>
          </div>
        </div>
      </div>
      <CapsuleButton
        variant="secondary"
        disabled={!valid || create.isPending}
        onClick={() => create.mutate()}
      >
        {create.isPending ? "Добавляем…" : "Добавить и выбрать"}
      </CapsuleButton>
      {create.isError && (
        <p className="mt-2 px-1 text-[12px] text-status-critical">Не удалось добавить прокси.</p>
      )}
    </div>
  );
}

function SessionSourceCard({
  sessionFile,
  setSessionFile,
  sessionString,
  setSessionString,
}: {
  sessionFile: File | null;
  setSessionFile: (f: File | null) => void;
  sessionString: string;
  setSessionString: (v: string) => void;
}) {
  return (
    <div className="mb-4 rounded-card border border-hairline bg-surface-1 p-4">
      <p className="mb-3 text-[13px] font-semibold text-text-primary">Источник сессии</p>
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
        Сессия шифруется перед записью в базу — в открытом виде не хранится. Аккаунт сразу
        попадёт в пул, код подтверждения не нужен.
      </InfoNote>
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

function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-1 flex gap-2.5 rounded-chip border border-hairline bg-surface-1 px-4 py-3">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
      <p className="text-[13px] leading-relaxed text-text-secondary">{children}</p>
    </div>
  );
}

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
        setStatus(r.detected_geo ? `Подобран под ${r.detected_geo}` : "Подобран свободный прокси");
      } else if (r.reason === "no_matching_geo_proxy") {
        setStatus(r.detected_geo ? `Нет свободного прокси для ${r.detected_geo}` : "Нет свободного прокси нужного гео");
      } else {
        setStatus("Свободных прокси нет");
      }
    },
    onError: () => setStatus("Ошибка подбора"),
  });
  const enabled = phone.trim().length >= 4 && !pick.isPending;
  return (
    <div className="mb-2 flex items-center gap-2">
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
