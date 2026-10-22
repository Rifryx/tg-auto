import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { AccountAvatar } from "../../../shared/AccountAvatar";
import { accountDisplay } from "../../../shared/format";
import type { Account } from "../../../shared/types";
import type { CampaignAccount, PostSelectionMode } from "../types";
import { CapsuleButton, RangeField, TextArea, Toggle } from "./ui";

/* Окно индивидуальных настроек аккаунта внутри кампании: свой промпт
   (перекрывает общий промпт кампании для этого аккаунта) и своя
   вероятность комментирования. Бэкенд уже принимает оба поля через
   PATCH /campaigns/{id}/accounts/{account_id} — раньше в UI детали
   кампании это было нечем редактировать. */
export function AccountCampaignSettingsSheet({
  open,
  account,
  link,
  campaignProbability,
  selectionMode,
  busy,
  onClose,
  onSave,
}: {
  open: boolean;
  account: Account | undefined;
  link: CampaignAccount | undefined;
  campaignProbability: number;
  selectionMode: PostSelectionMode;
  busy?: boolean;
  onClose: () => void;
  onSave: (patch: { override_prompt: string | null; probability_override: number | null }) => void;
}) {
  const [promptOn, setPromptOn] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [probOn, setProbOn] = useState(false);
  const [prob, setProb] = useState(campaignProbability);

  useEffect(() => {
    if (!open) return;
    setPromptOn(!!link?.override_prompt);
    setPrompt(link?.override_prompt ?? "");
    setProbOn(link?.probability_override != null);
    setProb(link?.probability_override ?? campaignProbability);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, link?.account_id]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)] lg:items-center lg:justify-center lg:p-8"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="mx-auto flex max-h-[85vh] w-full max-w-[440px] flex-col rounded-t-card border-t border-strong bg-bg-elevated lg:max-w-[520px] lg:rounded-card lg:border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <AccountAvatar avatarUrl={account?.avatar_url} fallback={account?.first_name ?? account?.username} size={32} />
            <div className="min-w-0">
              <h3 className="truncate text-[16px] font-semibold text-text-primary">
                {account ? accountDisplay(account) : "Аккаунт"}
              </h3>
              <p className="text-[12px] text-text-tertiary">Свои настройки в этой кампании</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-secondary hover:text-text-primary"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 [scrollbar-width:thin]">
          <div className="mb-4 rounded-chip border border-hairline bg-surface-1 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[14px] text-text-primary">Свой промпт</p>
                <p className="text-[12px] text-text-tertiary">
                  Полностью заменяет промпт кампании только для этого аккаунта.
                </p>
              </div>
              <Toggle checked={promptOn} onChange={setPromptOn} label="Свой промпт" />
            </div>
            {promptOn && (
              <TextArea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ты — активный участник обсуждений…"
              />
            )}
          </div>

          <div className="rounded-chip border border-hairline bg-surface-1 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[14px] text-text-primary">Своя вероятность</p>
                <p className="text-[12px] text-text-tertiary">
                  {selectionMode === "probability"
                    ? "Переопределяет общую вероятность кампании для этого аккаунта."
                    : `Учитывается только в режиме «По вероятности» (сейчас кампания в режиме другом).`}
                </p>
              </div>
              <Toggle checked={probOn} onChange={setProbOn} label="Своя вероятность" />
            </div>
            {probOn && (
              <RangeField label={`${prob}%`} value={prob} min={0} max={100} unit="%" onChange={setProb} />
            )}
          </div>
        </div>

        <div
          className="border-t border-hairline px-5 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 14px)" }}
        >
          <CapsuleButton
            disabled={busy}
            onClick={() =>
              onSave({
                override_prompt: promptOn && prompt.trim() ? prompt.trim() : null,
                probability_override: probOn ? prob : null,
              })
            }
          >
            {busy ? "Сохраняем…" : "Сохранить"}
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
