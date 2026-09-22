import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { Select } from "../../shared/Select";
import { maskPhone } from "../../shared/format";
import { statusDotClass } from "../../shared/status";
import { haptic } from "../../shared/tg";
import type { Account } from "../../shared/types";
import { commentingApi } from "./api";
import { AccountPickerSheet } from "./components/AccountPickerSheet";
import { CommentLogList } from "./components/CommentLogList";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  RangeField,
  Section,
  SegmentedControl,
  TextArea,
  TextInput,
  Toggle,
} from "./components/ui";
import type { CampaignUpdateBody, LLMProvider } from "./types";

const LLM_OPTIONS: { value: LLMProvider; label: string }[] = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "gemini", label: "Gemini" },
];

export function CampaignDetailScreen() {
  const { id } = useParams();
  const campaignId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [delayMin, setDelayMin] = useState<number | null>(null);
  const [delayMax, setDelayMax] = useState<number | null>(null);

  const campaign = useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => commentingApi.get(campaignId),
  });
  const links = useQuery({
    queryKey: ["campaign", campaignId, "accounts"],
    queryFn: () => commentingApi.accounts(campaignId),
  });
  const allAccounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const personas = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });
  const logs = useQuery({
    queryKey: ["campaign", campaignId, "logs"],
    queryFn: () => commentingApi.logs(campaignId),
    refetchInterval: 15_000,
  });

  const save = useMutation({
    mutationFn: (body: CampaignUpdateBody) => commentingApi.update(campaignId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaign", campaignId] }),
  });
  const attach = useMutation({
    mutationFn: (ids: number[]) => Promise.all(ids.map((a) => commentingApi.attach(campaignId, a))),
    onSuccess: () => {
      setSheetOpen(false);
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "accounts"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
  const detach = useMutation({
    mutationFn: (accountId: number) => commentingApi.detach(campaignId, accountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "accounts"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => commentingApi.remove(campaignId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      navigate("/tasks");
    },
  });

  const c = campaign.data;
  useEffect(() => {
    if (c) {
      setDelayMin((p) => (p == null ? c.posting_delay_min_sec : p));
      setDelayMax((p) => (p == null ? c.posting_delay_max_sec : p));
    }
  }, [c]);

  if (campaign.isLoading) return <div className="card mt-8 h-40 animate-pulse bg-surface-2" />;
  if (campaign.isError || !c)
    return <p className="pt-10 text-center text-[14px] text-status-critical">Кампания не найдена.</p>;

  const accountById = new Map<number, Account>((allAccounts.data ?? []).map((a) => [a.id, a]));
  const attachedIds = (links.data ?? []).map((l) => l.account_id);

  return (
    <div className="pb-6 pt-1">
      <button
        onClick={() => navigate("/tasks")}
        className="mb-3 inline-flex items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Кампании
      </button>

      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="screen-title truncate">{c.name}</h1>
        <Toggle
          checked={c.enabled}
          label={c.enabled ? "Приостановить" : "Возобновить"}
          onChange={(v) => {
            haptic("light");
            save.mutate({ enabled: v });
          }}
        />
      </div>

      {/* Настройки — автосохранение onBlur */}
      <Section title="Настройки">
        <div className="card p-4">
          <AutoText
            label="Название"
            value={c.name}
            onSave={(v) => save.mutateAsync({ name: v })}
          />
          <div className="mb-4">
            <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Модель</p>
            <SegmentedControl
              options={LLM_OPTIONS}
              value={c.llm_provider}
              onChange={(v) => save.mutate({ llm_provider: v })}
            />
          </div>
          <div className="mb-4">
            <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Персона (по умолчанию)</p>
            <Select
              value={c.persona_id != null ? String(c.persona_id) : ""}
              onChange={(v) => save.mutate({ persona_id: v === "" ? null : Number(v) })}
              placeholder="Без персоны"
              options={[
                { value: "", label: "Без персоны (голый промпт)" },
                ...(personas.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
              ]}
            />
          </div>
          <AutoText
            label="Промпт"
            value={c.base_system_prompt}
            textarea
            onSave={(v) => save.mutateAsync({ base_system_prompt: v })}
          />
          {delayMin != null && delayMax != null && (
            <>
              <RangeField
                label="Задержка мин."
                value={delayMin}
                min={5}
                max={600}
                onChange={(v) => setDelayMin(Math.min(v, delayMax))}
                onCommit={() => save.mutate({ posting_delay_min_sec: delayMin })}
              />
              <RangeField
                label="Задержка макс."
                value={delayMax}
                min={5}
                max={600}
                onChange={(v) => setDelayMax(Math.max(v, delayMin))}
                onCommit={() => save.mutate({ posting_delay_max_sec: delayMax })}
              />
            </>
          )}
        </div>
      </Section>

      {/* Аккаунты */}
      <Section
        title="Аккаунты"
        action={
          <button
            onClick={() => setSheetOpen(true)}
            className="inline-flex items-center gap-1 text-[13px] text-text-secondary active:text-text-primary"
          >
            <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
            Добавить
          </button>
        }
      >
        {attachedIds.length === 0 ? (
          <p className="px-1 text-[13px] text-text-tertiary">Аккаунты не привязаны.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {attachedIds.map((aid) => {
              const acc = accountById.get(aid);
              return (
                <div key={aid} className="card flex items-center gap-3 px-4 py-3">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${acc ? statusDotClass(acc.status) : "bg-status-neutral"}`}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate text-[15px] text-text-primary nums">
                    {acc ? maskPhone(acc.phone) : `Аккаунт #${aid}`}
                  </span>
                  <button
                    onClick={() => detach.mutate(aid)}
                    aria-label="Отвязать"
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
                  >
                    <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      <Section title="Стиль комментариев">
        <div className="card flex flex-col gap-3 p-4">
          <StyleToggle
            label="Использовать эмодзи"
            checked={c.use_emojis}
            onChange={(v) => save.mutate({ use_emojis: v })}
          />
          <StyleToggle
            label="Комментировать стикерами"
            hint="Runtime — DEFERRED [E4.1]."
            checked={c.use_stickers}
            onChange={(v) => save.mutate({ use_stickers: v })}
          />
          <StyleToggle
            label="Картинка к комментарию"
            hint="Runtime — DEFERRED [E4.1]."
            checked={c.attach_image}
            onChange={(v) => save.mutate({ attach_image: v })}
          />
          <StyleToggle
            label="Писать от имени канала"
            hint="Требует прав post_messages у аккаунта."
            checked={c.write_as_channel}
            onChange={(v) => save.mutate({ write_as_channel: v })}
          />
          <StyleToggle
            label="Контроль удаления комментариев"
            hint={`Через ${c.verify_delay_sec}с — тот же аккаунт (DEFERRED [E4.2]).`}
            checked={c.verify_after_post}
            onChange={(v) => save.mutate({ verify_after_post: v })}
          />
        </div>
      </Section>

      <CampaignChannelsSection campaignId={campaignId} />
      <CampaignBlacklistSection campaignId={campaignId} />

      {/* Лог */}
      <Section title="Лог комментариев">
        {logs.data ? <CommentLogList logs={logs.data} /> : <p className="text-[13px] text-text-tertiary">Загрузка…</p>}
      </Section>

      <CapsuleButton variant="danger" onClick={() => setConfirmDelete(true)}>
        Удалить кампанию
      </CapsuleButton>

      <AccountPickerSheet
        open={sheetOpen}
        excludeIds={attachedIds}
        busy={attach.isPending}
        onClose={() => setSheetOpen(false)}
        onAdd={(ids) => attach.mutate(ids)}
      />
      <ConfirmDialog
        open={confirmDelete}
        title="Удалить кампанию?"
        message="Кампания и её лог будут удалены безвозвратно. Привязанные аккаунты вернутся в пул."
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

/* Поле с автосохранением onBlur + едва заметная галочка «Сохранено» на 1.5 сек. */
function AutoText({
  label,
  value,
  onSave,
  textarea,
}: {
  label: string;
  value: string;
  onSave: (v: string) => Promise<unknown>;
  textarea?: boolean;
}) {
  const [v, setV] = useState(value);
  const [saved, setSaved] = useState(false);
  useEffect(() => setV(value), [value]);

  const commit = async () => {
    if (v.trim() === value || v.trim() === "") return;
    await onSave(v.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const hint = saved ? (
    <span className="inline-flex items-center gap-0.5 text-text-tertiary">
      <Check className="h-3 w-3" strokeWidth={2} aria-hidden />
      Сохранено
    </span>
  ) : undefined;

  return (
    <Field label={label} hint={hint}>
      {textarea ? (
        <TextArea value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} />
      ) : (
        <TextInput value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} />
      )}
    </Field>
  );
}

/* Компактный ряд «Тумблер + подпись» для секции стиля. */
function StyleToggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-[14px] text-text-primary">{label}</p>
        {hint && <p className="mt-0.5 text-[12px] text-text-tertiary">{hint}</p>}
      </div>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

/* ── Целевые каналы кампании (§ Этап 3) ─────────────────────────────
   Компактный менеджер: список + поле добавления одной строкой + удаление.
   Bulk-добавление живёт на NewCampaignScreen; тут — точечные правки. */
function CampaignChannelsSection({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["campaign", campaignId, "channels"],
    queryFn: () => commentingApi.channels(campaignId),
  });
  const [raw, setRaw] = useState("");
  const add = useMutation({
    mutationFn: (input: string) => commentingApi.addChannels(campaignId, [input]),
    onSuccess: () => {
      setRaw("");
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "channels"] });
    },
  });
  const remove = useMutation({
    mutationFn: (channelId: number) => commentingApi.removeChannel(campaignId, channelId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "channels"] }),
  });

  return (
    <Section title="Целевые каналы">
      <div className="card p-4">
        <div className="mb-3 flex gap-2">
          <TextInput
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder="@username или t.me/…"
          />
          <CapsuleButton
            variant="secondary"
            disabled={!raw.trim() || add.isPending}
            onClick={() => add.mutate(raw.trim())}
            className="w-auto px-4"
          >
            <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
          </CapsuleButton>
        </div>
        {list.data && list.data.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            {list.data.map((ch) => (
              <div
                key={ch.id}
                className="flex items-center justify-between rounded-chip border border-hairline bg-surface-1 px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-[14px] text-text-primary">{ch.raw_input}</p>
                  <p className="text-[11px] text-text-tertiary">
                    {ch.kind}
                    {ch.title && ` · ${ch.title}`}
                    {ch.last_error && (
                      <span className="ml-1 text-status-critical">
                        · {ch.last_error}
                      </span>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => remove.mutate(ch.id)}
                  aria-label="Удалить"
                  className="text-text-tertiary active:text-status-critical"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-text-tertiary">Каналы не заданы.</p>
        )}
      </div>
    </Section>
  );
}

/* ── Черный список каналов (§ Этап 3) ────────────────────────────────
   Ручное добавление username/chat_id + просмотр авто-добавленных
   воркером (auto=true). */
function CampaignBlacklistSection({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["campaign", campaignId, "blacklist"],
    queryFn: () => commentingApi.blacklist(campaignId),
  });
  const [value, setValue] = useState("");
  const add = useMutation({
    mutationFn: (input: string) => {
      const trimmed = input.trim();
      const asNum = Number(trimmed);
      return commentingApi.addBlacklist(campaignId, {
        chat_id: Number.isFinite(asNum) && !trimmed.startsWith("@") && trimmed !== "" ? asNum : null,
        username: !Number.isFinite(asNum) || trimmed.startsWith("@") ? trimmed.replace(/^@/, "") : null,
      });
    },
    onSuccess: () => {
      setValue("");
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "blacklist"] });
    },
  });
  const remove = useMutation({
    mutationFn: (entryId: number) => commentingApi.removeBlacklist(campaignId, entryId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "blacklist"] }),
  });

  return (
    <Section title="Чёрный список каналов">
      <div className="card p-4">
        <div className="mb-3 flex gap-2">
          <TextInput
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="@username или chat_id"
          />
          <CapsuleButton
            variant="secondary"
            disabled={!value.trim() || add.isPending}
            onClick={() => add.mutate(value.trim())}
            className="w-auto px-4"
          >
            <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
          </CapsuleButton>
        </div>
        {list.data && list.data.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            {list.data.map((it) => (
              <div
                key={it.id}
                className="flex items-center justify-between rounded-chip border border-hairline bg-surface-1 px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-[14px] text-text-primary">
                    {it.username ? `@${it.username}` : `chat_id ${it.chat_id}`}
                    {it.auto && (
                      <span className="ml-1.5 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] uppercase text-text-tertiary">
                        auto
                      </span>
                    )}
                  </p>
                  {it.reason && <p className="text-[11px] text-text-tertiary">{it.reason}</p>}
                </div>
                <button
                  onClick={() => remove.mutate(it.id)}
                  aria-label="Убрать из ЧС"
                  className="text-text-tertiary active:text-status-critical"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-text-tertiary">
            Пусто. Каналы с ошибками доступа попадают сюда автоматически.
          </p>
        )}
      </div>
    </Section>
  );
}
