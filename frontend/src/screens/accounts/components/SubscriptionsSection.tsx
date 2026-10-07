import { useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut } from "lucide-react";
import { useState } from "react";
import { Field, TextArea } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* Подписка/отписка аккаунта по ссылкам («Управление аккаунтом», этап 1).
 *
 * Поддерживает @username, t.me/name, инвайты t.me/+hash (= заявка на вступление
 * через ImportChatInvite) и папки-addlist — всё разбирает bulk-action
 * join_channels. Отписка — leave_channels. */
export function SubscriptionsSection({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const [refs, setRefs] = useState("");
  const job = useBulkJob(() => {
    // Подписки могли завести новые диалоги — обновим каналы мониторинга.
    qc.invalidateQueries({ queryKey: ["account", accountId, "channels"] });
  });

  const parsed = refs
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const busy = job.state.phase === "running";
  const result = job.state.firstResult as
    | { joined?: string[]; left?: string[]; errors?: Record<string, string> }
    | null;

  return (
    <Section title="Подписки и заявки">
      <div className="card p-4">
        <Field label="Ссылки на каналы, чаты или инвайты">
          <TextArea
            value={refs}
            onChange={(e) => setRefs(e.target.value)}
            placeholder="@channel, https://t.me/name, https://t.me/+AbCdEf… — по одной в строке или через запятую"
          />
        </Field>
        <p className="mb-3 px-1 text-[12px] text-text-tertiary">
          Инвайт-ссылки (t.me/+…) отправляют заявку на вступление в закрытые
          каналы/чаты. Папки-addlist разворачиваются автоматически.
        </p>

        <div className="flex gap-2">
          <CapsuleButton
            variant="accent"
            disabled={parsed.length === 0 || busy}
            onClick={() => job.run("join_channels", [accountId], { channel_refs: parsed })}
          >
            <span className="inline-flex items-center gap-2">
              <LogIn className="h-4 w-4" strokeWidth={2} aria-hidden />
              {busy ? "Выполняем…" : "Подписаться"}
            </span>
          </CapsuleButton>
          <CapsuleButton
            variant="secondary"
            disabled={parsed.length === 0 || busy}
            onClick={() => job.run("leave_channels", [accountId], { channel_refs: parsed })}
          >
            <span className="inline-flex items-center gap-2">
              <LogOut className="h-4 w-4" strokeWidth={2} aria-hidden />
              Отписаться
            </span>
          </CapsuleButton>
        </div>

        {job.state.phase === "failed" && (
          <p className="mt-3 text-[12px] text-status-critical">
            {job.state.error ?? "Не удалось выполнить."}
          </p>
        )}
        {job.state.phase === "done" && result && (
          <div className="mt-3 text-[12px]">
            {(result.joined?.length ?? 0) > 0 && (
              <p className="text-status-active">Подписок: {result.joined!.length}</p>
            )}
            {(result.left?.length ?? 0) > 0 && (
              <p className="text-status-active">Отписок: {result.left!.length}</p>
            )}
            {result.errors && Object.keys(result.errors).length > 0 && (
              <p className="text-status-warning">
                С ошибками: {Object.keys(result.errors).length}
              </p>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
