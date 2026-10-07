import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { ApiError } from "../../../shared/api";
import type { ProfilePreview } from "../../../shared/types";
import { Field, TextArea, TextInput } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* ИИ-оформление профиля («Управление аккаунтом», этап 1).
 *
 * 1. По персоне аккаунта генерируем превью (имя/фамилия/био/username-кандидаты)
 *    через POST /accounts/{id}/profile/generate-preview — без применения.
 * 2. Пользователь правит и жмёт «Применить» → bulk-action apply_profile для
 *    одного аккаунта (реально пишет в Telegram + синхронит нашу БД). */
export function AiProfileSection({
  accountId,
  hasPersona,
}: {
  accountId: number;
  hasPersona: boolean;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<ProfilePreview | null>(null);
  const [username, setUsername] = useState("");

  const generate = useMutation({
    mutationFn: () => accountsApi.generateProfilePreview(accountId),
    onSuccess: (p) => {
      setDraft(p);
      setUsername(p.username_candidates[0] ?? "");
    },
  });

  const apply = useBulkJob(() => {
    qc.invalidateQueries({ queryKey: ["account", accountId] });
  });

  const noPersona =
    generate.error instanceof ApiError && generate.error.status === 422;

  return (
    <Section title="ИИ-оформление профиля">
      {!draft && (
        <div className="card p-4">
          <p className="mb-3 flex items-start gap-2 text-[13px] text-text-secondary">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" strokeWidth={1.8} aria-hidden />
            Сгенерируем имя, фамилию, «о себе» и варианты @username по персоне
            аккаунта. Результат можно отредактировать перед применением.
          </p>
          {!hasPersona && (
            <p className="mb-3 text-[12px] text-text-tertiary">
              У аккаунта нет персоны — привяжите её в разделе «Персона» ниже,
              иначе генерировать не из чего.
            </p>
          )}
          {noPersona && (
            <p className="mb-2 text-[12px] text-status-critical">
              Нужна персона — привяжите её перед генерацией.
            </p>
          )}
          {generate.isError && !noPersona && (
            <p className="mb-2 text-[12px] text-status-critical">
              Не удалось сгенерировать. Попробуйте ещё раз.
            </p>
          )}
          <CapsuleButton
            variant={hasPersona ? "accent" : "secondary"}
            disabled={!hasPersona || generate.isPending}
            onClick={() => generate.mutate()}
          >
            <span className="inline-flex items-center gap-2">
              <Sparkles className="h-4 w-4" strokeWidth={2} aria-hidden />
              {generate.isPending ? "Генерируем…" : "Сгенерировать профиль"}
            </span>
          </CapsuleButton>
        </div>
      )}

      {draft && (
        <div className="card p-4">
          <div className="flex flex-col gap-3">
            <Field label="Имя">
              <TextInput
                value={draft.first_name}
                onChange={(e) => setDraft({ ...draft, first_name: e.target.value })}
              />
            </Field>
            <Field label="Фамилия">
              <TextInput
                value={draft.last_name}
                onChange={(e) => setDraft({ ...draft, last_name: e.target.value })}
              />
            </Field>
            <Field label="О себе">
              <TextArea
                value={draft.bio}
                maxLength={70}
                onChange={(e) => setDraft({ ...draft, bio: e.target.value })}
              />
            </Field>
            <Field label="@username">
              <TextInput
                value={username}
                onChange={(e) => setUsername(e.target.value.replace(/^@/, ""))}
                placeholder="username"
              />
            </Field>
            {draft.username_candidates.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                {draft.username_candidates.map((u) => (
                  <button
                    key={u}
                    onClick={() => setUsername(u)}
                    className={`rounded-full border px-2.5 py-1 text-[12px] ${
                      username === u
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-hairline bg-surface-2 text-text-secondary"
                    }`}
                  >
                    @{u}
                  </button>
                ))}
              </div>
            )}
          </div>

          {apply.state.phase === "failed" && (
            <p className="mt-3 text-[12px] text-status-critical">
              {apply.state.error ?? "Не удалось применить профиль."}
            </p>
          )}
          {apply.state.phase === "done" && (
            <p className="mt-3 flex items-center gap-1.5 text-[12px] text-status-active">
              <Check className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Профиль применён к Telegram.
            </p>
          )}

          <div className="mt-4 flex gap-2">
            <CapsuleButton
              variant="secondary"
              onClick={() => {
                setDraft(null);
                apply.reset();
                generate.reset();
              }}
            >
              <span className="inline-flex items-center gap-1">
                <X className="h-4 w-4" strokeWidth={2} aria-hidden />
                Сбросить
              </span>
            </CapsuleButton>
            <CapsuleButton
              variant="accent"
              disabled={apply.state.phase === "running"}
              onClick={() =>
                apply.run("apply_profile", [accountId], {
                  first_name: draft.first_name || null,
                  last_name: draft.last_name || null,
                  bio: draft.bio || null,
                  username_candidates: username.trim() ? [username.trim()] : [],
                })
              }
            >
              {apply.state.phase === "running" ? "Применяем…" : "Применить к Telegram"}
            </CapsuleButton>
          </div>
        </div>
      )}
    </Section>
  );
}
