import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, HeartPulse, Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { accountsApi, catalogApi, detachFromCampaign } from "../../shared/accounts";
import { formatDateTime, maskHost, maskPhone, timeAgo } from "../../shared/format";
import { PROFILE_LABEL, STATUS_LABEL, statusDotClass } from "../../shared/status";
import { haptic } from "../../shared/tg";
import type { WarmingProfile } from "../../shared/types";
import { Field, TextArea, TextInput } from "../../modules/commenting/components/ui";
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
  const detach = useMutation({
    mutationFn: () => detachFromCampaign(acc!.assigned_container_id!, accountId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account", accountId] }),
  });

  if (account.isLoading) return <DetailSkeleton />;
  if (account.isError || !acc)
    return (
      <div className="pt-2">
        <BackLink />
        <p className="mt-8 text-center text-[14px] text-status-critical">Аккаунт не найден.</p>
      </div>
    );

  const canDetach =
    acc.status === "assigned" &&
    acc.assigned_container_type === "commenting" &&
    acc.assigned_container_id != null;

  return (
    <div className="pt-1">
      <BackLink />
      <div className="mb-6 mt-1 flex items-center justify-between">
        <h1 className="screen-title nums">{maskPhone(acc.phone)}</h1>
        <StatusBadge status={acc.status} />
      </div>

      {/* Профиль — редактируемый (автосохранение onBlur). */}
      <Section title="Профиль">
        <div className="card p-4">
          <ProfileHeader avatarUrl={acc.avatar_url} username={acc.username} />
          <AutoField
            label="Юзернейм"
            value={acc.username ?? ""}
            placeholder="username"
            onSave={(v) => patchProfile.mutateAsync({ username: v || null })}
          />
          <AutoField
            label="Описание"
            value={acc.bio ?? ""}
            placeholder="Био профиля"
            textarea
            onSave={(v) => patchProfile.mutateAsync({ bio: v || null })}
          />
          <AutoField
            label="Аватар (URL)"
            value={acc.avatar_url ?? ""}
            placeholder="https://…"
            onSave={(v) => patchProfile.mutateAsync({ avatar_url: v || null })}
          />
        </div>
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

      {/* 3. Прокси */}
      <Section title="Прокси">
        {acc.proxy_id == null ? (
          <Muted>Прокси не привязан.</Muted>
        ) : proxy.data ? (
          <div className="flex items-center justify-between">
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
        ) : (
          <Muted>Загрузка…</Muted>
        )}
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

      {/* 5. Персона */}
      <Section title="Персона">
        {acc.persona_id == null ? (
          <Muted>Персона не назначена.</Muted>
        ) : persona.data ? (
          <div className="flex items-center gap-3">
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
        ) : (
          <Muted>Загрузка…</Muted>
        )}
      </Section>

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
        {canDetach && (
          <CapsuleButton
            variant="secondary"
            onClick={() => detach.mutate()}
            disabled={detach.isPending}
          >
            Отвязать от кампании
          </CapsuleButton>
        )}
        <CapsuleButton variant="danger" onClick={() => setConfirmRetire(true)}>
          Вывести аккаунт
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
function ProfileHeader({ avatarUrl, username }: { avatarUrl: string | null; username: string | null }) {
  return (
    <div className="mb-4 flex items-center gap-3">
      {avatarUrl ? (
        <img src={avatarUrl} alt="" className="h-12 w-12 rounded-full object-cover" />
      ) : (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-[18px] font-semibold text-text-secondary">
          {(username ?? "?").slice(0, 1).toUpperCase()}
        </div>
      )}
      <span className="text-[15px] text-text-primary">
        {username ? `@${username}` : "без юзернейма"}
      </span>
    </div>
  );
}

/* Поле профиля с автосохранением onBlur + галочка «Сохранено» на 1.5 сек. */
function AutoField({
  label,
  value,
  placeholder,
  textarea,
  onSave,
}: {
  label: string;
  value: string;
  placeholder?: string;
  textarea?: boolean;
  onSave: (v: string) => Promise<unknown>;
}) {
  const [v, setV] = useState(value);
  const [saved, setSaved] = useState(false);
  useEffect(() => setV(value), [value]);

  const commit = async () => {
    if (v.trim() === value.trim()) return;
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
        <TextArea value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} placeholder={placeholder} />
      ) : (
        <TextInput value={v} onChange={(e) => setV(e.target.value)} onBlur={commit} placeholder={placeholder} />
      )}
    </Field>
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
