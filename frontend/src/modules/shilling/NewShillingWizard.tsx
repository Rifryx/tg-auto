import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../shared/accounts";
import { maskPhone } from "../../shared/format";
import { AccountPickerSheet } from "../commenting/components/AccountPickerSheet";
import {
  CapsuleButton,
  Field,
  RangeField,
  SegmentedControl,
  TextArea,
  TextInput,
} from "../commenting/components/ui";
import { shillingApi } from "./api";
import { ScenarioBuilder } from "./components/ScenarioBuilder";
import type { LLMProvider } from "./types";

const LLM_OPTIONS: { value: LLMProvider; label: string }[] = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "gemini", label: "Gemini" },
];

interface Draft {
  name: string;
  brand_name: string;
  llm_provider: LLMProvider;
  accountIds: number[];
  targetsRaw: string;
  reply_min: number;
  reply_max: number;
  target_min: number;
  target_max: number;
  msg_limit_per_hour: string;
  msg_limit_total: string;
}

const INITIAL: Draft = {
  name: "",
  brand_name: "",
  llm_provider: "deepseek",
  accountIds: [],
  targetsRaw: "",
  reply_min: 5,
  reply_max: 15,
  target_min: 600,
  target_max: 1800,
  msg_limit_per_hour: "",
  msg_limit_total: "",
};

const STEPS = ["Основа", "Сценарий", "Запуск"];

export function NewShillingWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(INITIAL);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  // Кампания создаётся при переходе на шаг «Сценарий» — конструктору нужен
  // реальный campaignId (сценарий/роли/шаги пишутся через API кампании).
  const [draftId, setDraftId] = useState<number | null>(null);

  const basics = () => ({
    name: draft.name.trim(),
    brand_name: draft.brand_name.trim() || null,
    llm_provider: draft.llm_provider,
  });

  const ensureCampaign = useMutation({
    mutationFn: async () => {
      if (draftId != null) {
        await shillingApi.update(draftId, basics());
        return draftId;
      }
      const c = await shillingApi.create(basics());
      setDraftId(c.id);
      return c.id;
    },
    onSuccess: () => setStep(1),
    meta: { silent: true }, // inline-сообщение под кнопками
  });

  const finish = useMutation({
    mutationFn: async () => {
      let id = draftId;
      if (id == null) {
        const c = await shillingApi.create(basics());
        id = c.id;
        setDraftId(c.id);
      }
      await shillingApi.update(id, {
        reply_delay_min_sec: draft.reply_min,
        reply_delay_max_sec: draft.reply_max,
        target_delay_min_sec: draft.target_min,
        target_delay_max_sec: draft.target_max,
        msg_limit_per_hour: draft.msg_limit_per_hour ? Number(draft.msg_limit_per_hour) : null,
        msg_limit_total: draft.msg_limit_total ? Number(draft.msg_limit_total) : null,
      });
      for (const accId of draft.accountIds) {
        await shillingApi.attach(id, { account_id: accId }).catch(() => {});
      }
      const targets = draft.targetsRaw
        .split(/[\n,]/)
        .map((t) => t.trim())
        .filter(Boolean);
      if (targets.length) await shillingApi.addTargets(id, targets);
      return id;
    },
    onSuccess: (id) => navigate(`/modules/shilling/campaigns/${id}`),
    meta: { silent: true }, // inline-сообщение под кнопками
  });

  const step1Valid = draft.name.trim().length > 0 && draft.brand_name.trim().length > 0;

  return (
    <div className="pb-6 pt-1">
      <button
        onClick={() => navigate("/modules/shilling")}
        className="mb-3 inline-flex items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Кампании
      </button>

      <h1 className="screen-title mb-5">Новая кампания</h1>

      <Stepper current={step} />

      <div className="mt-6">
        {step === 0 && <StepBasics draft={draft} set={set} />}
        {step === 1 &&
          (draftId != null ? (
            <ScenarioBuilder campaignId={draftId} />
          ) : (
            <div className="card p-6 text-center text-[13px] text-text-tertiary">
              Подготавливаем кампанию…
            </div>
          ))}
        {step === 2 && <StepLaunch draft={draft} set={set} />}
      </div>

      <div className="mt-8 flex items-center gap-3">
        {step > 0 && (
          <CapsuleButton variant="secondary" onClick={() => setStep((s) => s - 1)}>
            Назад
          </CapsuleButton>
        )}
        {step === 0 && (
          <CapsuleButton
            variant={step1Valid ? "accent" : "secondary"}
            disabled={!step1Valid || ensureCampaign.isPending}
            onClick={() => ensureCampaign.mutate()}
          >
            {ensureCampaign.isPending ? "Готовим…" : "Далее"}
          </CapsuleButton>
        )}
        {step === 1 && (
          <CapsuleButton variant="accent" onClick={() => setStep(2)}>
            Далее
          </CapsuleButton>
        )}
        {step === 2 && (
          <CapsuleButton
            variant="accent"
            disabled={finish.isPending || !step1Valid}
            onClick={() => finish.mutate()}
          >
            {finish.isPending ? "Создаём…" : "Создать кампанию"}
          </CapsuleButton>
        )}
      </div>

      {(ensureCampaign.isError || finish.isError) && (
        <p className="mt-3 text-[13px] text-status-critical">
          Что-то пошло не так. Проверьте данные и попробуйте снова.
        </p>
      )}
    </div>
  );
}

function Stepper({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEPS.map((label, i) => (
        <div key={label} className="flex flex-1 items-center last:flex-none">
          <div className="flex flex-col items-center gap-1">
            <div
              className={[
                "flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-semibold",
                i < current
                  ? "bg-accent text-accent-on"
                  : i === current
                    ? "bg-surface-2 text-text-primary ring-2 ring-accent"
                    : "bg-surface-2 text-text-tertiary",
              ].join(" ")}
            >
              {i < current ? <Check className="h-4 w-4" strokeWidth={2.5} aria-hidden /> : i + 1}
            </div>
            <span className="text-[11px] text-text-tertiary">{label}</span>
          </div>
          {i < STEPS.length - 1 && (
            <div
              className={[
                "mx-2 mb-4 h-0.5 flex-1",
                i < current ? "bg-accent" : "bg-surface-2",
              ].join(" ")}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function StepBasics({
  draft,
  set,
}: {
  draft: Draft;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}) {
  return (
    <div className="card flex flex-col gap-4 p-4">
      <Field label="Название кампании">
        <TextInput
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Напр.: Beauty Zone — весна"
        />
      </Field>
      <Field
        label="Бренд / ключевая фраза"
        hint="Как будет упоминаться в диалоге — текстом, без ссылок"
      >
        <TextInput
          value={draft.brand_name}
          onChange={(e) => set("brand_name", e.target.value)}
          placeholder="Напр.: Beauty Zone"
        />
      </Field>
      <div>
        <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Модель ИИ</p>
        <SegmentedControl
          options={LLM_OPTIONS}
          value={draft.llm_provider}
          onChange={(v) => set("llm_provider", v)}
        />
      </div>
    </div>
  );
}

function StepLaunch({
  draft,
  set,
}: {
  draft: Draft;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const targetsCount = draft.targetsRaw
    .split(/[\n,]/)
    .map((t) => t.trim())
    .filter(Boolean).length;

  return (
    <div className="flex flex-col gap-4">
      {/* Аккаунты */}
      <div className="card p-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[14px] font-medium text-text-primary">Аккаунты</p>
          <button
            onClick={() => setSheetOpen(true)}
            className="text-[13px] text-accent active:opacity-80"
          >
            Выбрать
          </button>
        </div>
        {draft.accountIds.length === 0 ? (
          <p className="text-[13px] text-text-tertiary">Аккаунты не выбраны.</p>
        ) : (
          <SelectedAccounts
            ids={draft.accountIds}
            onRemove={(id) => set("accountIds", draft.accountIds.filter((x) => x !== id))}
          />
        )}
      </div>

      {/* Цели */}
      <div className="card p-4">
        <p className="mb-2 text-[14px] font-medium text-text-primary">
          Цели <span className="text-text-tertiary">· {targetsCount}</span>
        </p>
        <TextArea
          value={draft.targetsRaw}
          onChange={(e) => set("targetsRaw", e.target.value)}
          placeholder="@username, t.me/… — по одному в строке"
          rows={4}
        />
      </div>

      {/* Тайминги */}
      <div className="card p-4">
        <RangeField
          label="Пауза между репликами (мин)"
          value={draft.reply_min}
          min={0}
          max={120}
          onChange={(v) => set("reply_min", Math.min(v, draft.reply_max))}
        />
        <RangeField
          label="Пауза между репликами (макс)"
          value={draft.reply_max}
          min={0}
          max={120}
          onChange={(v) => set("reply_max", Math.max(v, draft.reply_min))}
        />
        <RangeField
          label="Пауза между целями (мин)"
          value={draft.target_min}
          min={0}
          max={3600}
          onChange={(v) => set("target_min", Math.min(v, draft.target_max))}
        />
        <RangeField
          label="Пауза между целями (макс)"
          value={draft.target_max}
          min={0}
          max={3600}
          onChange={(v) => set("target_max", Math.max(v, draft.target_min))}
        />
      </div>

      {/* Лимиты */}
      <div className="card flex flex-col gap-4 p-4">
        <Field label="Лимит сообщений/час на аккаунт" hint="Пусто — без лимита">
          <TextInput
            inputMode="numeric"
            value={draft.msg_limit_per_hour}
            onChange={(e) => set("msg_limit_per_hour", e.target.value.replace(/\D/g, ""))}
            placeholder="без лимита"
          />
        </Field>
        <Field label="Всего сообщений на аккаунт" hint="Пусто — без лимита">
          <TextInput
            inputMode="numeric"
            value={draft.msg_limit_total}
            onChange={(e) => set("msg_limit_total", e.target.value.replace(/\D/g, ""))}
            placeholder="без лимита"
          />
        </Field>
      </div>

      {/* Sanity-check */}
      <div className="card flex flex-col gap-2 p-4">
        <CheckRow ok={draft.accountIds.length > 0} label={`Аккаунты: ${draft.accountIds.length}`} />
        <CheckRow ok={targetsCount > 0} label={`Цели: ${targetsCount}`} />
        <CheckRow ok label="Сценарий собран на шаге 2" muted />
      </div>

      <AccountPickerSheet
        open={sheetOpen}
        excludeIds={draft.accountIds}
        onClose={() => setSheetOpen(false)}
        onAdd={(ids) => {
          set("accountIds", [...draft.accountIds, ...ids]);
          setSheetOpen(false);
        }}
      />
    </div>
  );
}

function SelectedAccounts({
  ids,
  onRemove,
}: {
  ids: number[];
  onRemove: (id: number) => void;
}) {
  const { data } = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => accountsApi.list(),
  });
  const byId = new Map((data ?? []).map((a) => [a.id, a]));
  return (
    <div className="flex flex-col gap-1.5">
      {ids.map((id) => {
        const acc = byId.get(id);
        return (
          <div
            key={id}
            className="flex items-center justify-between rounded-chip border border-hairline bg-surface-1 px-3 py-2"
          >
            <span className="truncate text-[14px] text-text-primary nums">
              {acc ? maskPhone(acc.phone) : `Аккаунт #${id}`}
            </span>
            <button
              onClick={() => onRemove(id)}
              aria-label="Убрать"
              className="text-text-tertiary active:text-status-critical"
            >
              <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function CheckRow({ ok, label, muted }: { ok: boolean; label: string; muted?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[13px]">
      <span
        className={[
          "flex h-5 w-5 items-center justify-center rounded-full",
          ok ? "bg-status-active/20 text-status-active" : "bg-surface-2 text-text-tertiary",
        ].join(" ")}
      >
        {ok ? <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden /> : "○"}
      </span>
      <span className={muted ? "text-text-tertiary" : "text-text-secondary"}>{label}</span>
    </div>
  );
}
