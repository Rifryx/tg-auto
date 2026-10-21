import { Copy, Pin, PinOff } from "lucide-react";
import { useState } from "react";
import { Field, TextInput } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* Закрепить/открепить ПРОИЗВОЛЬНЫЙ канал или чат в списке диалогов аккаунта —
   по @username или ссылке t.me (не только созданные приложением каналы).
   Расположено рядом с профилем, как просили: «в блоке с изменением имени/авы». */
export function PinChannelSection({ accountId }: { accountId: number }) {
  const [ref, setRef] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const job = useBulkJob((detail) => {
    const result = detail.items[0]?.result as
      | { link?: string | null; username?: string | null }
      | undefined;
    // Ссылку берём из ответа (t.me/username для публичных); иначе строим из ref.
    const derived =
      result?.link ||
      (result?.username ? `https://t.me/${result.username}` : normalizeLink(ref));
    setLink(derived ?? null);
  });

  const busy = job.state.phase === "running";
  const valid = ref.trim().length > 0;

  const pin = (pinned: boolean) =>
    job.run("pin_channel_ref", [accountId], { ref: ref.trim(), pinned });

  return (
    <Section title="Закрепить канал/чат в аккаунте">
      <div className="card p-4">
        <p className="mb-3 text-[13px] text-text-secondary">
          Укажите @username или ссылку на канал/чат, на который у аккаунта есть
          доступ — он закрепится в его списке диалогов.
        </p>
        <Field label="Канал или чат">
          <TextInput
            value={ref}
            onChange={(e) => {
              setRef(e.target.value);
              setLink(null);
            }}
            placeholder="@durov или https://t.me/durov"
          />
        </Field>

        <div className="mt-2 flex gap-2">
          <CapsuleButton variant="accent" disabled={!valid || busy} onClick={() => pin(true)}>
            <span className="inline-flex items-center gap-2">
              <Pin className="h-4 w-4" strokeWidth={2} aria-hidden />
              {busy ? "Закрепляем…" : "Закрепить"}
            </span>
          </CapsuleButton>
          <CapsuleButton variant="secondary" disabled={!valid || busy} onClick={() => pin(false)}>
            <span className="inline-flex items-center gap-2">
              <PinOff className="h-4 w-4" strokeWidth={2} aria-hidden />
              Открепить
            </span>
          </CapsuleButton>
        </div>

        {job.state.phase === "failed" && (
          <p className="mt-2 text-[12px] text-status-critical">
            {job.state.error ?? "Не удалось. Проверьте, что аккаунт имеет доступ к этому каналу/чату."}
          </p>
        )}
        {job.state.phase === "done" && (
          <div className="mt-3">
            <p className="mb-1 text-[12px] text-status-active">Готово.</p>
            {link && (
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard
                    ?.writeText(link)
                    .then(() => {
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1500);
                    })
                    .catch(() => {});
                }}
                className="flex w-full items-center gap-2 rounded-chip border border-hairline bg-surface-2 px-3 py-2 text-left active:bg-surface-1"
              >
                <span className="min-w-0 flex-1 truncate text-[13px] text-text-primary nums">
                  {link}
                </span>
                <Copy
                  className={`h-3.5 w-3.5 shrink-0 ${copied ? "text-status-active" : "text-text-tertiary"}`}
                  strokeWidth={1.8}
                  aria-hidden
                />
              </button>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

function normalizeLink(ref: string): string | null {
  const r = ref.trim();
  if (!r) return null;
  if (r.startsWith("http")) return r;
  if (r.startsWith("@")) return `https://t.me/${r.slice(1)}`;
  if (r.startsWith("t.me/")) return `https://${r}`;
  return `https://t.me/${r}`;
}
