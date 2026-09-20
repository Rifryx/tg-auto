import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Camera, Check, HeartPulse, Lock, Radio, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { accountsApi, catalogApi, channelsApi } from "../../shared/accounts";
import { Select } from "../../shared/Select";
import { commentingApi } from "../../modules/commenting/api";
import { formatDateTime, maskHost, maskPhone, timeAgo } from "../../shared/format";
import { PROFILE_LABEL, STATUS_LABEL, statusDotClass } from "../../shared/status";
import { haptic } from "../../shared/tg";
import type { MonitoredChannel, MonitoredChannelStatus, WarmingProfile } from "../../shared/types";
import { Field, TextArea, Toggle } from "../../modules/commenting/components/ui";
import { BanRiskCard } from "./components/BanRiskCard";
import { CapsuleButton, ConfirmDialog, Section, SegmentedControl, StatusBadge } from "./components/ui";

const PROFILE_OPTIONS: { value: WarmingProfile; label: string }[] = [
  { value: "minimal", label: PROFILE_LABEL.minimal },
  { value: "medium", label: PROFILE_LABEL.medium },
  { value: "dense", label: PROFILE_LABEL.dense },
];

export function AccountDetailScreen() {
  const { id } = useParams();
  const accountId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const account = useQuery({
    queryKey: ["account", accountId],
    queryFn: () => accountsApi.get(accountId),
    refetchInterval: 15_000, // живое обновление видимой карточки
  });
  const history = useQuery({
    queryKey: ["account", accountId, "history"],
    queryFn: () => accountsApi.history(accountId),
    refetchInterval: 15_000,
  });
  const warming = useQuery({
    queryKey: ["account", accountId, "warming"],
    queryFn: () => accountsApi.warming(accountId),
    refetchInterval: 15_000,
  });
  const acc = account.data;
  const proxy = useQuery({
    queryKey: ["proxy", acc?.proxy_id],
    queryFn: () => catalogApi.proxy(acc!.proxy_id!),
    enabled: acc?.proxy_id != null,
  });
  const personasList = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });
  const proxiesList = useQuery({ queryKey: ["proxies"], queryFn: catalogApi.proxies });
  const campaignsList = useQuery({ queryKey: ["campaigns"], queryFn: commentingApi.list });
  const persona = useQuery({
    queryKey: ["persona", acc?.persona_id],
    queryFn: () => catalogApi.personas().then((all) => all.find((p) => p.id === acc!.persona_id) ?? null),
    enabled: acc?.persona_id != null,
  });

  const setProfile = useMutation({
    mutationFn: (p: WarmingProfile) => accountsApi.setProfile(accountId, p),
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["account", accountId] });
    },
  });
  const patchProfile = useMutation({
    mutationFn: (body: Parameters<typeof accountsApi.patch>[1]) =>
      accountsApi.patch(accountId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", accountId] }),
  });
  const retire = useMutation({
    mutationFn: () => accountsApi.retire(accountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      navigate("/accounts");
    },
  });
  const remove = useMutation({
    mutationFn: () => accountsApi.remove(accountId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      navigate("/accounts");
    },
  });
  const restore = useMutation({
    mutationFn: () => accountsApi.restore(accountId),
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["account", accountId] });
    },
  });
  // Перемещение между кампаниями одним действием: снять из текущей + добавить в
  // новую (state machine требует POOL между привязками).
  const currentCampaignId =
    acc?.assigned_container_type === "commenting" ? acc?.assigned_container_id ?? null : null;
  const moveCampaign = useMutation({
    mutationFn: async (target: number | null) => {
      if (currentCampaignId != null) await commentingApi.detach(currentCampaignId, accountId);
      if (target != null) await commentingApi.attach(target, accountId);
    },
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["account", accountId] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });

  if (account.isLoading) return <DetailSkeleton />;
  if (account.isError || !acc)
    return (
      <div className="pt-2">
        <BackLink />
        <p className="mt-8 text-center text-[14px] text-status-critical">Аккаунт не найден.</p>
      </div>
    );

  return (
    <div className="pt-1">
      <BackLink />
      <div className="mb-6 mt-1 flex items-center justify-between">
        <h1 className="screen-title nums">{maskPhone(acc.phone)}</h1>
        <StatusBadge status={acc.status} />
      </div>

      {/* Профиль — редактируемый в стиле Telegram (автосохранение onBlur). */}
      <Section title="Профиль">
        <div className="card p-4">
          <AvatarPicker
            avatarUrl={acc.avatar_url}
            fallback={acc.first_name || acc.username}
            onPick={(dataUrl) => patchProfile.mutateAsync({ avatar_url: dataUrl })}
            onClear={() => patchProfile.mutateAsync({ avatar_url: null })}
          />
        </div>

        {/* Группа «Имя» в стиле сгруппированного списка Telegram. */}
        <TgGroup caption="Имя и фамилия отображаются в Telegram у собеседников.">
          <TgField
            label="Имя"
            value={acc.first_name ?? ""}
            placeholder="Имя"
            onSave={(v) => patchProfile.mutateAsync({ first_name: v || null })}
          />
          <TgField
            label="Фамилия"
            value={acc.last_name ?? ""}
            placeholder="Фамилия (необязательно)"
            onSave={(v) => patchProfile.mutateAsync({ last_name: v || null })}
          />
        </TgGroup>

        <TgGroup caption="Люди смогут найти аккаунт по этому имени пользователя и написать ему.">
          <TgField
            label="@"
            mono
            value={acc.username ?? ""}
            placeholder="username"
            onSave={(v) => patchProfile.mutateAsync({ username: v.replace(/^@/, "") || null })}
          />
        </TgGroup>

        <TgGroup caption={`О себе — коротко. ${70 - (acc.bio?.length ?? 0)} симв.`}>
          <TgField
            label="О себе"
            value={acc.bio ?? ""}
            placeholder="Немного о себе"
            textarea
            maxLength={70}
            onSave={(v) => patchProfile.mutateAsync({ bio: v || null })}
          />
        </TgGroup>
      </Section>

      {/* 1. Статус + таймлайн переходов */}
      <Section title="Статус">
        {history.data && history.data.length > 0 ? (
          <ol className="flex flex-col">
            {history.data
              .slice()
              .reverse()
              .map((rec, i) => (
                <li
                  key={rec.id}
                  className={`flex items-start gap-3 py-2.5 ${i > 0 ? "border-t border-hairline" : ""}`}
                >
                  <span
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${statusDotClass(rec.to_status)}`}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] text-text-primary">
                      {STATUS_LABEL[rec.to_status]}
                      {rec.from_status ? (
                        <span className="text-text-tertiary"> · из {STATUS_LABEL[rec.from_status]}</span>
                      ) : null}
                    </p>
                    <p className="text-[12px] text-text-tertiary">
                      {rec.initiator} · {formatDateTime(rec.created_at)}
                    </p>
                  </div>
                </li>
              ))}
          </ol>
        ) : (
          <Muted>История переходов пуста.</Muted>
        )}
      </Section>

      {/* 2. Здоровье (пер-аккаунт эндпоинта нет — задел под будущий API) */}
      <Section title="Здоровье">
        <div className="flex items-center gap-2 text-[14px] text-text-secondary">
          <HeartPulse className="h-4 w-4 text-text-tertiary" strokeWidth={1.6} aria-hidden />
          Инцидентов нет
        </div>
      </Section>

      {/* 2b. Anti-ban predictor (этап 11) */}
      <BanRiskCard accountId={accountId} />

      {/* 3. Прокси — read-инфо + смена через селект */}
      <Section title="Прокси">
        {acc.proxy_id != null && proxy.data && (
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-[14px] text-text-primary nums">
                {maskHost(proxy.data.host)}:{proxy.data.port}
              </p>
              <p className="text-[12px] text-text-tertiary">
                {proxy.data.type.toUpperCase()} · {proxy.data.geo ?? "—"}
              </p>
            </div>
            <div className="flex items-center gap-1.5 text-[13px] text-text-secondary">
              <span
                className={`h-2 w-2 rounded-full ${proxy.data.status === "alive" ? "bg-status-active" : proxy.data.status === "dead" ? "bg-status-critical" : "bg-status-neutral"}`}
                aria-hidden
              />
              {proxy.data.status === "alive" ? "жив" : proxy.data.status === "dead" ? "мёртв" : "не пров."}
            </div>
          </div>
        )}
        <Select
          value={acc.proxy_id != null ? String(acc.proxy_id) : ""}
          onChange={(v) => patchProfile.mutate({ proxy_id: v === "" ? null : Number(v) })}
          disabled={patchProfile.isPending}
          options={[
            { value: "", label: "Без прокси" },
            ...(proxiesList.data ?? []).map((p) => ({
              value: String(p.id),
              label: `${maskHost(p.host)}:${p.port} · ${p.type.toUpperCase()} · ${p.status}`,
            })),
          ]}
        />
      </Section>

      {/* 4. Фингерпринт — read-only, приглушённый, иммутабельный */}
      <Section title="Фингерпринт">
        <div className="space-y-1.5 text-[13px] text-text-secondary">
          <FpRow label="Устройство" value={acc.device_model} />
          <FpRow label="Система" value={acc.system_version} />
          <FpRow label="Приложение" value={acc.app_version} />
          <FpRow label="Язык" value={`${acc.lang_code} / ${acc.system_lang_code}`} />
        </div>
        <div className="mt-3 flex items-center gap-1.5 text-[12px] text-text-tertiary">
          <Lock className="h-3 w-3" strokeWidth={1.8} aria-hidden />
          Неизменяемо
        </div>
      </Section>

      {/* 5. Персона — смена/снятие через селект */}
      <Section title="Персона">
        {acc.persona_id != null && persona.data && (
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-[15px] font-semibold text-text-secondary">
              {persona.data.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-[14px] text-text-primary">{persona.data.name}</p>
              <p className="truncate text-[12px] text-text-tertiary">
                {persona.data.personality_tags.join(" · ") || "без тегов"}
              </p>
            </div>
          </div>
        )}
        <Select
          value={acc.persona_id != null ? String(acc.persona_id) : ""}
          onChange={(v) => patchProfile.mutate({ persona_id: v === "" ? null : Number(v) })}
          disabled={patchProfile.isPending}
          options={[
            { value: "", label: "Без персоны (голый промпт)" },
            ...(personasList.data ?? []).map((p) => ({
              value: String(p.id),
              label: p.name,
            })),
          ]}
        />
        {personasList.data && personasList.data.length === 0 && (
          <p className="mt-2 text-[12px] text-text-tertiary">
            Персон пока нет — создать можно в разделе «Ещё».
          </p>
        )}
      </Section>

      {/* Кампания — перемещение между кампаниями одним действием. */}
      {(acc.status === "pool" || acc.status === "assigned") && (
        <Section title="Кампания">
          <Select
            value={currentCampaignId != null ? String(currentCampaignId) : ""}
            onChange={(v) => moveCampaign.mutate(v === "" ? null : Number(v))}
            disabled={moveCampaign.isPending}
            placeholder="Не в кампании"
            options={[
              { value: "", label: "Не в кампании" },
              ...(campaignsList.data ?? []).map((c) => ({ value: String(c.id), label: c.name })),
            ]}
          />
          {moveCampaign.isPending && (
            <p className="mt-2 text-[12px] text-text-tertiary">Перемещаем…</p>
          )}
          {moveCampaign.isError && (
            <p className="mt-2 text-[12px] text-status-critical">
              Не удалось переместить (аккаунт должен быть свободен).
            </p>
          )}
        </Section>
      )}

      {/* Каналы мониторинга — свой список каналов у каждого аккаунта. */}
      <ChannelsSection accountId={accountId} />

      {/* 6. Пресет прогрева — сегмент-контрол → PATCH без перезагрузки */}
      <Section title="Пресет прогрева">
        <SegmentedControl
          options={PROFILE_OPTIONS}
          value={acc.warming_profile}
          onChange={(p) => setProfile.mutate(p)}
          disabled={setProfile.isPending}
        />
      </Section>

      {/* 7. Активность прогрева */}
      <Section title="Активность">
        {warming.data && warming.data.length > 0 ? (
          <ul className="flex flex-col">
            {warming.data.slice(0, 12).map((a, i) => (
              <li
                key={a.id}
                className={`flex items-center justify-between py-2 ${i > 0 ? "border-t border-hairline" : ""}`}
              >
                <span className="text-[13px] text-text-primary">{a.action_type}</span>
                <span className="flex items-center gap-2 text-[12px] text-text-tertiary">
                  {timeAgo(a.created_at)}
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${a.status === "done" ? "bg-status-active" : a.status === "failed" ? "bg-status-critical" : "bg-status-neutral"}`}
                    aria-hidden
                  />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Muted>Пока нет активности.</Muted>
        )}
      </Section>

      {/* Действия — в потоке, не плавающие */}
      <div className="mt-2 flex flex-col gap-2 pb-4">
        {acc.status === "retired" && (
          <CapsuleButton onClick={() => restore.mutate()} disabled={restore.isPending}>
            {restore.isPending ? "Возвращаем…" : "Вернуть в пул"}
          </CapsuleButton>
        )}
        {acc.status !== "retired" && (
          <CapsuleButton variant="secondary" onClick={() => setConfirmRetire(true)}>
            Вывести аккаунт
          </CapsuleButton>
        )}
        <CapsuleButton variant="danger" onClick={() => setConfirmDelete(true)}>
          Удалить безвозвратно
        </CapsuleButton>
      </div>

      <ConfirmDialog
        open={confirmRetire}
        title="Вывести аккаунт?"
        message="Аккаунт перейдёт в статус «Выведен» и исчезнет из активных фильтров. Действие необратимо."
        confirmLabel="Вывести"
        danger
        busy={retire.isPending}
        onConfirm={() => retire.mutate()}
        onCancel={() => setConfirmRetire(false)}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="Удалить аккаунт?"
        message="Аккаунт и все его данные (история, прогрев, каналы, привязка к кампании) будут удалены безвозвратно."
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link
      to="/accounts"
      className="inline-flex items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
    >
      <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      Аккаунты
    </Link>
  );
}

function FpRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-text-tertiary">{label}</span>
      <span className="truncate text-right text-text-secondary">{value}</span>
    </div>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] text-text-tertiary">{children}</p>;
}


/* Аватар + юзернейм над полями профиля. */
/* Уменьшает выбранное фото до 512px и возвращает data-URL (JPEG) —
   чтобы не хранить в БД мегабайты. */
async function fileToAvatarDataUrl(file: File): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result as string);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("bad image"));
    el.src = dataUrl;
  });
  const max = 512;
  const scale = Math.min(1, max / Math.max(img.width, img.height));
  const w = Math.round(img.width * scale);
  const h = Math.round(img.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d")?.drawImage(img, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", 0.85);
}

/* Аватар с камерой (загрузка фото с устройства) — как в редакторе профиля TG. */
function AvatarPicker({
  avatarUrl,
  fallback,
  onPick,
  onClear,
}: {
  avatarUrl: string | null;
  fallback: string | null;
  onPick: (dataUrl: string) => Promise<unknown>;
  onClear: () => Promise<unknown>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // разрешаем повторный выбор того же файла
    if (!file) return;
    setBusy(true);
    try {
      await onPick(await fileToAvatarDataUrl(file));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col items-center gap-2 py-1">
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="relative h-[88px] w-[88px] rounded-full"
        aria-label="Загрузить фото"
      >
        {avatarUrl ? (
          <img src={avatarUrl} alt="" className="h-[88px] w-[88px] rounded-full object-cover" />
        ) : (
          <span className="flex h-[88px] w-[88px] items-center justify-center rounded-full bg-surface-2 text-[32px] font-semibold text-text-secondary">
            {(fallback ?? "?").slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full bg-accent text-accent-on ring-2 ring-surface-1">
          <Camera className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={onFile}
        className="hidden"
      />
      {avatarUrl && (
        <button
          onClick={() => onClear()}
          className="text-[13px] text-status-critical active:opacity-70"
        >
          Удалить фото
        </button>
      )}
      {busy && <p className="text-[12px] text-text-tertiary">Загрузка…</p>}
    </div>
  );
}

/* Сгруппированный список в стиле Telegram: карточка с рядами + подпись снизу. */
function TgGroup({ caption, children }: { caption?: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="overflow-hidden rounded-card border border-hairline bg-surface-1">
        {children}
      </div>
      {caption && <p className="mt-1.5 px-3 text-[12px] leading-snug text-text-tertiary">{caption}</p>}
    </div>
  );
}

/* Ряд редактируемого поля: подпись слева, инпут во всю ширину, автосейв onBlur. */
function TgField({
  label,
  value,
  placeholder,
  textarea,
  mono,
  maxLength,
  onSave,
}: {
  label: string;
  value: string;
  placeholder?: string;
  textarea?: boolean;
  mono?: boolean;
  maxLength?: number;
  onSave: (v: string) => Promise<unknown>;
}) {
  const [v, setV] = useState(value);
  const [saved, setSaved] = useState(false);
  useEffect(() => setV(value), [value]);

  const commit = async () => {
    if (v.trim() === value.trim()) return;
    await onSave(v.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
  };

  const inputCls = `min-h-[24px] flex-1 bg-transparent text-[16px] text-text-primary placeholder:text-text-tertiary outline-none ${mono ? "font-mono" : ""}`;

  return (
    <div className="flex items-start gap-3 border-b border-hairline px-4 py-3 last:border-b-0">
      <span className="mt-0.5 w-[76px] shrink-0 text-[15px] text-text-secondary">{label}</span>
      {textarea ? (
        <textarea
          value={v}
          maxLength={maxLength}
          onChange={(e) => setV(e.target.value)}
          onBlur={commit}
          placeholder={placeholder}
          rows={2}
          className={`${inputCls} resize-none`}
        />
      ) : (
        <input
          value={v}
          maxLength={maxLength}
          onChange={(e) => setV(e.target.value)}
          onBlur={commit}
          placeholder={placeholder}
          className={inputCls}
        />
      )}
      {saved && <Check className="mt-1 h-4 w-4 shrink-0 text-status-active" strokeWidth={2} aria-hidden />}
    </div>
  );
}

const CH_STATUS: Record<MonitoredChannelStatus, { label: string; dot: string }> = {
  pending: { label: "в очереди", dot: "bg-status-neutral" },
  working: { label: "в работе", dot: "bg-status-active" },
  paused: { label: "пауза", dot: "bg-status-warning" },
  failed: { label: "ошибка", dot: "bg-status-critical" },
};

/* Каналы аккаунта: добавление по ссылкам/папке + список со снятием с работы. */
function ChannelsSection({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const [refs, setRefs] = useState("");
  const [isFolder, setIsFolder] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<MonitoredChannel | null>(null);
  const [alsoUnsub, setAlsoUnsub] = useState(false);

  const channels = useQuery({
    queryKey: ["account", accountId, "channels"],
    queryFn: () => channelsApi.list(accountId),
    refetchInterval: 15_000, // pending → working обновляется воркером
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["account", accountId, "channels"] });

  const add = useMutation({
    mutationFn: (list: string[]) => channelsApi.add(accountId, list, isFolder),
    onSuccess: () => {
      haptic("light");
      setRefs("");
      setIsFolder(false);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: ({ id, unsub }: { id: number; unsub: boolean }) =>
      channelsApi.remove(accountId, id, unsub),
    onSuccess: () => {
      setRemoveTarget(null);
      setAlsoUnsub(false);
      invalidate();
    },
  });

  const parsed = refs
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const rows = channels.data ?? [];

  return (
    <Section title="Каналы мониторинга">
      <div className="mb-4 border-b border-hairline pb-4">
        <Field
          label={isFolder ? "Ссылка на папку (addlist)" : "Ссылки или @юзернеймы каналов"}
        >
          <TextArea
            value={refs}
            onChange={(e) => setRefs(e.target.value)}
            placeholder={
              isFolder
                ? "https://t.me/addlist/AbCdEf…"
                : "https://t.me/durov, @telegram — по одному в строке или через запятую"
            }
          />
        </Field>
        <label className="mb-4 flex items-center justify-between px-1">
          <span className="text-[14px] text-text-secondary">Это папка каналов</span>
          <Toggle checked={isFolder} onChange={setIsFolder} label="Папка каналов" />
        </label>
        <CapsuleButton
          onClick={() => add.mutate(parsed)}
          disabled={parsed.length === 0 || add.isPending}
        >
          {add.isPending
            ? "Добавляю…"
            : parsed.length > 1
              ? `Добавить (${parsed.length})`
              : "Добавить в работу"}
        </CapsuleButton>
      </div>

      {channels.isLoading ? (
        <Muted>Загрузка…</Muted>
      ) : rows.length === 0 ? (
        <Muted>Каналы не добавлены. Аккаунт пока ничего не мониторит.</Muted>
      ) : (
        <ul className="flex flex-col">
          {rows.map((ch, i) => {
            const meta = CH_STATUS[ch.status];
            return (
              <li
                key={ch.id}
                className={`flex items-center gap-3 py-2.5 ${i > 0 ? "border-t border-hairline" : ""}`}
              >
                <Radio className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.6} aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] text-text-primary">
                    {ch.title ?? ch.channel_ref ?? ch.input_ref}
                    {ch.is_folder && (
                      <span className="ml-1.5 text-[12px] text-text-tertiary">· папка</span>
                    )}
                  </p>
                  <p className="flex items-center gap-1.5 text-[12px] text-text-tertiary">
                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
                    {meta.label}
                    {ch.subscribed && <span>· подписан</span>}
                    {ch.error && <span className="text-status-critical">· {ch.error}</span>}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setAlsoUnsub(false);
                    setRemoveTarget(ch);
                  }}
                  aria-label="Снять канал с работы"
                  className="shrink-0 rounded-full p-1.5 text-text-tertiary active:text-status-critical"
                >
                  <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog
        open={removeTarget !== null}
        title="Снять канал с работы?"
        message={
          removeTarget
            ? `«${removeTarget.title ?? removeTarget.input_ref}» перестанет мониториться. Подписка в Telegram по умолчанию сохраняется.`
            : ""
        }
        confirmLabel={alsoUnsub ? "Снять и отписаться" : "Снять с работы"}
        danger={alsoUnsub}
        busy={remove.isPending}
        onConfirm={() =>
          removeTarget && remove.mutate({ id: removeTarget.id, unsub: alsoUnsub })
        }
        onCancel={() => setRemoveTarget(null)}
      >
        <label className="mt-3 flex items-center justify-between">
          <span className="text-[14px] text-text-secondary">Отписаться в Telegram</span>
          <Toggle checked={alsoUnsub} onChange={setAlsoUnsub} label="Отписаться в Telegram" />
        </label>
      </ConfirmDialog>
    </Section>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4 pt-6">
      <div className="h-8 w-40 animate-pulse rounded-chip bg-surface-2" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="card h-28 animate-pulse bg-surface-2" />
      ))}
    </div>
  );
}
