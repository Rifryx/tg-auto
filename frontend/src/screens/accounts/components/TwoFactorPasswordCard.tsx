import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { Field, TextInput } from "../../../modules/commenting/components/ui";
import { CapsuleButton, ConfirmDialog, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* Двухфакторный пароль аккаунта («Управление аккаунтом», этап 1).
 *
 * Статус 2FA берём из health-снапшота (has_2fa). Установка/смена/снятие —
 * через POST /accounts/bulk/set-2fa (plaintext шифруется на сервере, в
 * bulk_jobs.payload уходит уже зашифрованный blob). Задание асинхронное —
 * отслеживаем его через useBulkJob.track. */
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
  const [hint, setHint] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);

  const job = useBulkJob(() => {
    qc.invalidateQueries({ queryKey: ["account", accountId, "health"] });
    setEditing(false);
    setPassword("");
    setConfirmPwd("");
    setHint("");
  });

  const setMut = useMutation({
    mutationFn: (body: Parameters<typeof accountsApi.set2fa>[0]) =>
      accountsApi.set2fa(body),
    onSuccess: (jobRead) => job.track(jobRead.id),
  });

  const has2fa = health.data?.has_2fa ?? false;
  const busy = setMut.isPending || job.state.phase === "running";
  const mismatch = password.length > 0 && confirmPwd.length > 0 && password !== confirmPwd;
  const canSubmit = password.length >= 1 && password === confirmPwd && !busy;

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
            {job.state.phase === "done" && (
              <p className="mt-1 text-[12px] text-status-active">Применено.</p>
            )}
            {job.state.phase === "failed" && (
              <p className="mt-1 text-[12px] text-status-critical">
                {job.state.error ?? "Не удалось применить."}
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
                onClick={() => setConfirmRemove(true)}
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
                ? "Сменим текущий 2FA-пароль. Старый берётся из системы автоматически."
                : "Задайте новый 2FA-пароль. Он сохранится в зашифрованном виде."}
            </span>
          </div>
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
              {job.state.error ?? "Не удалось применить. Попробуйте ещё раз."}
            </p>
          )}
          <div className="flex gap-2">
            <CapsuleButton
              variant="secondary"
              onClick={() => {
                setEditing(false);
                setPassword("");
                setConfirmPwd("");
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
                  hint: hint.trim() || undefined,
                })
              }
            >
              {busy ? "Применяем…" : has2fa ? "Сменить пароль" : "Установить пароль"}
            </CapsuleButton>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmRemove}
        title="Снять 2FA-пароль?"
        message="Двухфакторная защита будет отключена. Аккаунт станет уязвимее к угону."
        confirmLabel="Снять"
        danger
        busy={busy}
        onConfirm={() => {
          setConfirmRemove(false);
          setMut.mutate({ account_ids: [accountId], mode: "remove" });
        }}
        onCancel={() => setConfirmRemove(false)}
      />
    </Section>
  );
}
