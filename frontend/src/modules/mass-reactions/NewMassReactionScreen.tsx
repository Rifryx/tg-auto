import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { StickyActionBar } from "../../components/StickyActionBar";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Select } from "../../shared/Select";
import { humanizeError } from "../../shared/api";
import { massReactionsApi } from "./api";
import { HUMANIZER_LABEL, REACTION_EMOJIS, WARMUP_LABEL } from "./labels";
import type {
  ChatSourceMode,
  HumanizerMode,
  WarmupProfile,
} from "./types";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-text-secondary">{label}</span>
      {children}
    </label>
  );
}

const INPUT =
  "w-full rounded-chip border border-hairline bg-surface-2 px-3.5 py-2.5 text-[14px] text-text-primary outline-none focus:border-strong";

export function NewMassReactionScreen() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [emojis, setEmojis] = useState<string[]>(["👍", "🔥"]);
  const [source, setSource] = useState<ChatSourceMode>("by_subscriptions");
  const [everyN, setEveryN] = useState("1");
  const [probability, setProbability] = useState("100");
  const [duration, setDuration] = useState("24");
  const [dailyLimit, setDailyLimit] = useState("200");
  const [maxChats, setMaxChats] = useState("5");
  const [warmup, setWarmup] = useState<WarmupProfile>("warm");
  const [humanizer, setHumanizer] = useState<HumanizerMode>("balanced");

  const toggleEmoji = (e: string) =>
    setEmojis((prev) => (prev.includes(e) ? prev.filter((x) => x !== e) : [...prev, e]));

  const create = useMutation({
    mutationFn: () =>
      massReactionsApi.create({
        name: name.trim(),
        reaction_emojis: emojis,
        chat_source_mode: source,
        every_n_message: Math.max(1, Number(everyN) || 1),
        probability_percent: Math.min(100, Math.max(1, Number(probability) || 100)),
        duration_hours: Math.min(72, Math.max(1, Number(duration) || 24)),
        daily_limit_per_account: Math.min(500, Math.max(1, Number(dailyLimit) || 200)),
        max_chats_per_account: Math.min(20, Math.max(1, Number(maxChats) || 5)),
        warmup_profile: warmup,
        humanizer_mode: humanizer,
      }),
    onSuccess: (c) => navigate(`/modules/mass-reactions/campaigns/${c.id}`, { replace: true }),
  });

  const canSubmit = name.trim().length > 0 && emojis.length > 0;

  return (
    <>
      <ScreenHeader title="Новая кампания" />

      <div className="flex flex-col gap-5">
        <Field label="Название">
          <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} placeholder="Напр. Реакции по крипточатам" />
        </Field>

        <div>
          <span className="mb-1.5 block text-[13px] font-medium text-text-secondary">Реакции</span>
          <div className="flex flex-wrap gap-2">
            {REACTION_EMOJIS.map((e) => {
              const on = emojis.includes(e);
              return (
                <button
                  key={e}
                  type="button"
                  onClick={() => toggleEmoji(e)}
                  className={`flex h-11 w-11 items-center justify-center rounded-chip border text-[20px] transition-colors ${
                    on ? "border-strong bg-surface-2" : "border-hairline bg-surface-1 opacity-60"
                  }`}
                >
                  {e}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[12px] text-text-tertiary">
            Из выбранных берётся случайная на каждую реакцию.
          </p>
        </div>

        <Field label="Источник чатов">
          <Select
            value={source}
            onChange={(v) => setSource(v as ChatSourceMode)}
            options={[
              { value: "by_subscriptions", label: "По подпискам аккаунтов" },
              { value: "explicit_list", label: "По списку (добавлю вручную)" },
            ]}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Реагировать на каждое N-е">
            <Select
              value={everyN}
              onChange={setEveryN}
              options={["1", "2", "3", "5"].map((n) => ({ value: n, label: `${n}-е` }))}
            />
          </Field>
          <Field label="Вероятность, %">
            <input inputMode="numeric" value={probability} onChange={(e) => setProbability(e.target.value.replace(/\D/g, ""))} className={`${INPUT} tabular-nums`} />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Длительность, ч">
            <input inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value.replace(/\D/g, ""))} className={`${INPUT} tabular-nums`} />
          </Field>
          <Field label="Макс. чатов на аккаунт">
            <input inputMode="numeric" value={maxChats} onChange={(e) => setMaxChats(e.target.value.replace(/\D/g, ""))} className={`${INPUT} tabular-nums`} />
          </Field>
        </div>

        <Field label="Дневной лимит реакций на аккаунт">
          <input inputMode="numeric" value={dailyLimit} onChange={(e) => setDailyLimit(e.target.value.replace(/\D/g, ""))} className={`${INPUT} tabular-nums`} />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Прогрев">
            <Select value={warmup} onChange={(v) => setWarmup(v as WarmupProfile)}
              options={(["cold", "warm", "hot"] as WarmupProfile[]).map((p) => ({ value: p, label: WARMUP_LABEL[p] }))} />
          </Field>
          <Field label="Антидетект">
            <Select value={humanizer} onChange={(v) => setHumanizer(v as HumanizerMode)}
              options={(["off", "balanced", "aggressive"] as HumanizerMode[]).map((m) => ({ value: m, label: HUMANIZER_LABEL[m] }))} />
          </Field>
        </div>

        {create.isError && <ErrorBanner message={humanizeError(create.error)} />}
      </div>

      <StickyActionBar>
        <button
          type="button"
          disabled={!canSubmit || create.isPending}
          onClick={() => create.mutate()}
          className="flex min-h-[48px] w-full items-center justify-center rounded-pill bg-accent px-5 text-[15px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
        >
          {create.isPending ? "Создаю…" : "Создать кампанию"}
        </button>
      </StickyActionBar>
    </>
  );
}
