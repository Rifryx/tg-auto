import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck, ShieldX, X } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { Field, TextInput } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* Двухфакторный пароль аккаунта («Управление аккаунтом», этап 1).
 *
 * Статус 2FA берём из health-снапшота (has_2fa). Установка/смена/снятие —
 * через POST /accounts/bulk/set-2fa (plaintext шифруется на сервере, в
 * bulk_jobs.payload уходит уже зашифрованный blob). Задание асинхронное —
 * отслеживаем его через useBulkJob.track.
 *
 * ВАЖНО: Telegram требует current_password при любом изменении/снятии 2FA.
 * Если в системе он сохранён — используем автоматически. Если нет (импорт
 * сессии без ввода пароля) или устарел (меняли вручную) — спрашиваем у
 * пользователя явно, иначе edit_2fa всегда падает PasswordHashInvalid. */
export function TwoFactorPasswordCard({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const health = useQuery({
    queryKey: ["account", accountId, "health"],
    queryFn: () => accountsApi.health(accountId),
    refetchInterval: 5_000,
  });

  const [editing, setEditing] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [currentPwd, setCurrentPwd] = useState("");
  const [hint, setHint] = useState("");
  const [removeOpen, setRemoveOpen] = useState(false);
  const [removeCurrentPwd, setRemoveCurrentPwd] = useState("");

  const job = useBulkJob(() => {
    qc.invalidateQueries({ queryKey: ["account", accountId, "health"] });
    void health.refetch();
    setEditing(false);
    setPassword("");
    setConfirmPwd("");
    setCurrentPwd("");
    setHint("");
    setRemoveOpen(false);
    setRemoveCurrentPwd("");
  });

  const setMut = useMutation({
    mutationFn: (body: Parameters<typeof accountsApi.set2fa>[0]) =>
      accountsApi.set2fa(body),
    onSuccess: (jobRead) => job.track(jobRead.id),
  });

  const has2fa = health.data?.has_2fa ?? false;
  const busy = setMut.isPending || job.state.phase === "running";
  const mismatch = password.length > 0 && confirmPwd.length > 0 && password !== confirmPwd;
  // Текущий пароль обязателен, если 2FA уже стоит (Telegram требует для
  // любого изменения). При первой установке — не нужен.
  const canSubmit =
    password.length >= 1
    && password === confirmPwd
    && (!has2fa || currentPwd.length >= 1)
    && !busy;

  // Явная причина skipped/failed с сервера → показываем понятный текст.
  const serverReason = (job.state.firstResult as { reason?: string } | null)?.reason;
  const serverError = (job.state.firstResult as { error?: string } | null)?.error;
  const friendlyServerMsg = reasonToText(serverReason, serverError);

  return (
    <Section title="Двухфакторный пароль">
      {!editing ? (
        <div className="card flex items-start gap-3 p-4">
          {has2fa ? (
            <ShieldCheck className="mt-0.5 h-5 w-5 text-status-active" strokeWidth={1.8} aria-hidden />
          ) : (
            <ShieldX className="mt-0.5 h-5 w-5 text-text-tertiary" strokeWidth={1.8} aria-hidden />
          )}
          <div className="flex-1">
            <p className="text-[15px] text-text-primary">
              {has2fa ? "2FA-пароль установлен" : "2FA-пароль не установлен"}
            </p>
            <p className="text-[12px] text-text-tertiary">
              {has2fa
                ? "Пароль хранится в системе в зашифрованном виде для авто-входа."
                : "Установите пароль, чтобы защитить аккаунт от угона."}
            </p>
            {/* «Применено» — только для реально успешной операции. Если item
                помечен skipped (нечего менять / нет пароля) или reason-поле
                непустое — показываем конкретный текст. */}
            {job.state.phase === "done" && !serverReason && (
              <p className="mt-1 text-[12px] text-status-active">Применено.</p>
            )}
            {job.state.phase === "done" && serverReason && (
              <p className="mt-1 text-[12px] text-status-warning">
                {friendlyServerMsg}
              </p>
            )}
            {job.state.phase === "failed" && (
              <p className="mt-1 text-[12px] text-status-critical">
                {friendlyServerMsg ?? job.state.error ?? "Не удалось применить."}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <button
              onClick={() => setEditing(true)}
              className="rounded-full border border-hairline bg-surface-2 px-3 py-1 text-[12px] text-text-secondary active:text-text-primary"
            >
              {has2fa ? "Сменить" : "Установить"}
            </button>
            {has2fa && (
              <button
                onClick={() => setRemoveOpen(true)}
                className="rounded-full px-3 py-1 text-[12px] text-status-critical active:opacity-70"
              >
                Снять
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="card p-4">
          <div className="mb-3 flex items-start gap-2 text-[13px] text-text-secondary">
            <KeyRound className="mt-0.5 h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
            <span>
              {has2fa
                ? "Чтобы сменить 2FA-пароль, Telegram требует ввести текущий."
                : "Задайте новый 2FA-пароль. Он сохранится в зашифрованном виде."}
            </span>
          </div>
          {has2fa && (
            <Field label="Текущий пароль">
              <TextInput
                value={currentPwd}
                onChange={(e) => setCurrentPwd(e.target.value)}
                type="password"
                autoComplete="current-password"
                placeholder="Введите текущий 2FA-пароль"
              />
            </Field>
          )}
          <Field label="Новый пароль">
            <TextInput
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete="new-password"
            />
          </Field>
          <Field label="Повторите пароль">
            <TextInput
              value={confirmPwd}
              onChange={(e) => setConfirmPwd(e.target.value)}
              type="password"
              autoComplete="new-password"
            />
          </Field>
          <Field label="Подсказка (необязательно)">
            <TextInput value={hint} onChange={(e) => setHint(e.target.value)} maxLength={255} />
          </Field>
          {mismatch && (
            <p className="mb-2 text-[12px] text-status-critical">Пароли не совпадают.</p>
          )}
          {(setMut.isError || job.state.phase === "failed") && (
            <p className="mb-2 text-[12px] text-status-critical">
              {friendlyServerMsg ?? job.state.error ?? "Не удалось применить. Попробуйте ещё раз."}
            </p>
          )}
          <div className="flex gap-2">
            <CapsuleButton
              variant="secondary"
              onClick={() => {
                setEditing(false);
                setPassword("");
                setConfirmPwd("");
                setCurrentPwd("");
                setHint("");
              }}
            >
              Отмена
            </CapsuleButton>
            <CapsuleButton
              variant={canSubmit ? "accent" : "secondary"}
              disabled={!canSubmit}
              onClick={() =>
                setMut.mutate({
                  account_ids: [accountId],
                  mode: "set_or_change",
                  password,
                  current_password: has2fa ? currentPwd : undefined,
                  hint: hint.trim() || undefined,
                })
              }
            >
              {busy ? "Применяем…" : has2fa ? "Сменить пароль" : "Установить пароль"}
            </CapsuleButton>
          </div>
        </div>
      )}

      {removeOpen && (
        <RemovePasswordSheet
          busy={busy}
          error={friendlyServerMsg ?? (job.state.phase === "failed" ? job.state.error : null)}
          value={removeCurrentPwd}
          onChange={setRemoveCurrentPwd}
          onCancel={() => {
            setRemoveOpen(false);
            setRemoveCurrentPwd("");
          }}
          onConfirm={() =>
            setMut.mutate({
              account_ids: [accountId],
              mode: "remove",
              current_password: removeCurrentPwd || undefined,
            })
          }
        />
      )}
    </Section>
  );
}

/* Переводит технические reason-коды с бэкенда в понятный текст. */
function reasonToText(
  reason: string | undefined,
  error: string | undefined,
): string | null {
  if (!reason && !error) return null;
  switch (reason) {
    case "no_2fa":
      return "У аккаунта нет 2FA-пароля — нечего снимать.";
    case "need_current_password":
      return "Текущий 2FA-пароль не сохранён в системе. Введите его вручную — Telegram требует его для снятия/смены.";
    case "invalid_current_password_enc":
      return "Не удалось расшифровать введённый пароль. Попробуйте ещё раз.";
    case "cannot_decrypt_current":
      return "Сохранённый пароль нечитаем. Введите текущий пароль вручную.";
    case "new_password_required":
      return "Новый пароль обязателен.";
    case "account_missing":
    case "account_gone":
      return "Аккаунт недоступен.";
    case "edit_2fa_failed":
      // Чаще всего — PasswordHashInvalidError (неправильный текущий пароль).
      if (error && /PasswordHashInvalid/i.test(error)) {
        return "Telegram отклонил текущий пароль. Проверьте его и повторите.";
      }
      if (error && /SessionPasswordNeeded/i.test(error)) {
        return "Для этого действия Telegram требует текущий пароль.";
      }
      return "Telegram отклонил операцию. Проверьте пароль и повторите.";
    default:
      return error || null;
  }
}

/* Модалка снятия пароля с полем «Текущий пароль». */
function RemovePasswordSheet({
  busy,
  error,
  value,
  onChange,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  error: string | null;
  value: string;
  onChange: (v: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center lg:p-6">
      <div onClick={onCancel} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        className="relative mx-auto w-full max-w-[440px] rounded-t-[28px] border border-hairline bg-bg-elevated p-5 pb-[calc(env(safe-area-inset-bottom)+16px)] lg:rounded-[28px] lg:pb-5"
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <h2 className="text-[18px] font-bold text-text-primary">
              Снять 2FA-пароль?
            </h2>
            <p className="mt-1 text-[12px] text-text-tertiary">
              Двухфакторная защита будет отключена. Аккаунт станет уязвимее к угону.
            </p>
          </div>
          <button
            onClick={onCancel}
            aria-label="Закрыть"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>
        <Field label="Текущий 2FA-пароль">
          <TextInput
            value={value}
            onChange={(e) => onChange(e.target.value)}
            type="password"
            autoComplete="current-password"
            placeholder="Пароль, который сейчас стоит на аккаунте"
            autoFocus
          />
        </Field>
        <p className="mb-3 text-[11px] leading-relaxed text-text-tertiary">
          Если пароль был сохранён при входе — поле можно оставить пустым,
          попробуем автоматически.
        </p>
        {error && (
          <p className="mb-2 text-[12px] text-status-critical">{error}</p>
        )}
        <div className="flex gap-2">
          <CapsuleButton variant="secondary" onClick={onCancel} disabled={busy}>
            Отмена
          </CapsuleButton>
          <CapsuleButton variant="danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Снимаем…" : "Снять пароль"}
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
