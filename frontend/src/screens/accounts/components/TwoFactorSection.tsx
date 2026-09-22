import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, Check, Mail, MailCheck, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import {
  CapsuleButton,
  Field,
  Section,
  TextInput,
} from "../../../modules/commenting/components/ui";

/* Секция «Управление 2FA» на карточке аккаунта (этап 7, backlog #1).
 *
 * MVP: только привязка/смена recovery-email (сам пароль ставится через
 * bulk-action set_2fa). Три состояния:
 *   1. У аккаунта нет recovery email → форма (email + текущий пароль)
 *   2. Ждём код (pending) → форма для ввода кода
 *   3. Email привязан → показать email + кнопка «Привязать другой»
 *
 * Опрос состояния — каждые 3 секунды (worker публикует событие в pub/sub,
 * но проще через polling; SSE-подписку добавим при необходимости).
 */
export function TwoFactorSection({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const state = useQuery({
    queryKey: ["account", accountId, "recovery-email"],
    queryFn: () => accountsApi.recoveryEmailState(accountId),
    refetchInterval: 3_000,
  });

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [replacing, setReplacing] = useState(false);

  const request = useMutation({
    mutationFn: () => accountsApi.requestRecoveryEmail(accountId, email.trim(), password),
    onSuccess: () => {
      setPassword("");
      qc.invalidateQueries({ queryKey: ["account", accountId, "recovery-email"] });
    },
  });
  const confirm = useMutation({
    mutationFn: () => accountsApi.confirmRecoveryEmail(accountId, code.trim()),
    onSuccess: () => {
      setCode("");
      qc.invalidateQueries({ queryKey: ["account", accountId, "recovery-email"] });
    },
  });

  const s = state.data;

  // Если сервер сказал «confirmed» — сбрасываем локальный replace-mode.
  useEffect(() => {
    if (s?.email && !s.pending_email) setReplacing(false);
  }, [s?.email, s?.pending_email]);

  if (!s) {
    return null;
  }

  // 2. Pending: ждём код.
  if (s.pending_email) {
    const codeLength = s.code_length ?? 6;
    const canSubmit = code.trim().length === codeLength && !confirm.isPending;
    return (
      <Section title="Управление 2FA">
        <div className="card p-4">
          <div className="mb-3 flex items-center gap-2 text-[13px] text-text-secondary">
            <Mail className="h-4 w-4 text-warning" strokeWidth={1.8} aria-hidden />
            Код отправлен на <span className="text-text-primary">{s.pending_email}</span>
          </div>
          <Field label={`Код из письма (${codeLength} цифр)`}>
            <TextInput
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              maxLength={codeLength}
              placeholder={"".padStart(codeLength, "0")}
            />
          </Field>
          {confirm.isError && (
            <p className="mb-2 text-[12px] text-danger">
              Не удалось подтвердить: код неверен или устарел.
            </p>
          )}
          <CapsuleButton
            variant={canSubmit ? "accent" : "secondary"}
            disabled={!canSubmit}
            onClick={() => confirm.mutate()}
          >
            <span className="inline-flex items-center gap-2">
              <Check className="h-4 w-4" strokeWidth={2} aria-hidden />
              {confirm.isPending ? "Подтверждаем…" : "Подтвердить"}
            </span>
          </CapsuleButton>
        </div>
      </Section>
    );
  }

  // 3. Email уже привязан — если пользователь не жмёт «Сменить».
  if (s.email && !replacing) {
    return (
      <Section title="Управление 2FA">
        <div className="card flex items-start gap-3 p-4">
          <MailCheck className="mt-0.5 h-5 w-5 text-success" strokeWidth={1.8} aria-hidden />
          <div className="flex-1">
            <p className="text-[15px] text-text-primary">Recovery email привязан</p>
            <p className="text-[12px] text-text-tertiary">{s.email}</p>
            {s.confirmed_at && (
              <p className="mt-1 text-[11px] text-text-tertiary">
                Подтверждён: {new Date(s.confirmed_at).toLocaleString()}
              </p>
            )}
          </div>
          <button
            onClick={() => setReplacing(true)}
            className="rounded-full border border-hairline bg-surface-2 px-3 py-1 text-[12px] text-text-secondary active:text-text-primary"
          >
            Сменить
          </button>
        </div>
      </Section>
    );
  }

  // 1. Форма запроса (нет email привязан ИЛИ replacing).
  const canRequest =
    email.trim().length >= 5 &&
    email.includes("@") &&
    password.length > 0 &&
    !request.isPending;

  return (
    <Section title="Управление 2FA">
      <div className="card p-4">
        <div className="mb-4 flex items-start gap-2 text-[13px] text-text-secondary">
          <ShieldCheck
            className="mt-0.5 h-4 w-4 text-text-tertiary"
            strokeWidth={1.8}
            aria-hidden
          />
          <span>
            Привяжите email — сможете восстановить 2FA-пароль, если он потерян.
            Email будет привязан к текущему паролю аккаунта.
          </span>
        </div>
        <Field label="Email">
          <TextInput
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="user@example.com"
            autoComplete="off"
          />
        </Field>
        <Field
          label="Текущий 2FA-пароль"
          hint={
            <span className="text-[11px] text-text-tertiary">
              Используется только для подтверждения, в БД не хранится.
            </span>
          }
        >
          <TextInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            autoComplete="off"
          />
        </Field>
        {request.isError && (
          <p className="mb-2 text-[12px] text-danger">
            Не удалось начать привязку. Проверьте, что 2FA настроена и пароль
            верный.
          </p>
        )}
        <div className="flex gap-2">
          {replacing && (
            <CapsuleButton
              variant="secondary"
              onClick={() => {
                setReplacing(false);
                setEmail("");
                setPassword("");
              }}
            >
              <span className="inline-flex items-center gap-1">
                <X className="h-4 w-4" strokeWidth={2} aria-hidden />
                Отмена
              </span>
            </CapsuleButton>
          )}
          <CapsuleButton
            variant={canRequest ? "accent" : "secondary"}
            disabled={!canRequest}
            onClick={() => request.mutate()}
          >
            <span className="inline-flex items-center gap-2">
              <AtSign className="h-4 w-4" strokeWidth={2} aria-hidden />
              {request.isPending ? "Отправляем код…" : "Отправить код"}
            </span>
          </CapsuleButton>
        </div>
      </div>
    </Section>
  );
}
