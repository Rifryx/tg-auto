import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, History, Plus, UserPlus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { accountDisplay } from "../../../shared/format";
import { Select } from "../../../shared/Select";
import { AccountPickerSheet } from "../../commenting/components/AccountPickerSheet";
import { shillingApi } from "../api";
import type { CampaignAccount, CampaignUpdateBody, Role, Target, TargetMode } from "../types";
import { DualRange } from "./DualRange";
import { HintDot } from "./HintDot";
import { RoleAvatar } from "./RoleCard";

/* Экран «Запуск» — одно место, где видно всё, что нужно для старта кампании:
   сценарий, цели, аккаунты с ролями, параметры и темп. Раньше это было
   размазано по пяти вкладкам, и перед стартом приходилось обходить их все. */

const MODE_TABS: { value: TargetMode; label: string; hint: string; placeholder: string }[] = [
  {
    value: "chat",
    label: "Чаты",
    hint: "Диалог идёт прямо в чате/группе — обычными сообщениями, а не комментариями под постом.",
    placeholder: "@chat или t.me/chat — по одной в строке",
  },
  {
    value: "channel_monitor",
    label: "Мониторинг каналов",
    hint: "Выберите каналы — софт сам поймает новые посты и запустит диалог в комментариях. Ссылки на посты не нужны.",
    placeholder: "@channel или t.me/channel — по одной в строке",
  },
  {
    value: "link",
    label: "Ссылки",
    hint: "Универсальный режим: у канала с обсуждением комментируем последний пост, в группу пишем напрямую.",
    placeholder: "@channel, t.me/chat, t.me/+invite — по одной в строке",
  },
  {
    value: "channel_post",
    label: "Посты каналов",
    hint: "Диалог в комментариях под конкретными постами.",
    placeholder: "t.me/channel/123 — по одной в строке",
  },
];

/** Ссылка на конкретный пост — считаем их, чтобы показать «Распознано постов». */
const POST_LINK_RE =
  /(?:https?:\/\/)?t\.me\/(?:c\/)?(?:[A-Za-z0-9_]{3,32}|\d+)\/\d+\s*$/i;

function splitLines(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function LaunchTab({
  campaignId,
  onEditScenario,
  onOpenHistory,
}: {
  campaignId: number;
  onEditScenario: () => void;
  onOpenHistory: () => void;
}) {
  const qc = useQueryClient();

  const campaign = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });
  const scenario = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "scenario"],
    queryFn: () => shillingApi.scenario(campaignId),
    retry: false,
  });
  const roles = useQuery({
    queryKey: ["shilling", "scenario", scenario.data?.id, "roles"],
    queryFn: () => shillingApi.roles(scenario.data!.id),
    enabled: scenario.data?.id != null,
  });
  const steps = useQuery({
    queryKey: ["shilling", "scenario", scenario.data?.id, "steps"],
    queryFn: () => shillingApi.steps(scenario.data!.id),
    enabled: scenario.data?.id != null,
  });
  const readiness = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "readiness"],
    queryFn: () => shillingApi.readiness(campaignId),
    refetchInterval: 5000,
  });

  const patch = useMutation({
    mutationFn: (body: CampaignUpdateBody) => shillingApi.update(campaignId, body),
    onSuccess: (updated) =>
      qc.setQueryData(["shilling", "campaign", campaignId], updated),
  });

  const c = campaign.data;
  if (!c) return <div className="card h-64 animate-pulse bg-surface-2" />;

  const roleList: Role[] = roles.data ?? [];
  const stepCount = steps.data?.length ?? 0;
  const problems = readiness.data
    ? [readiness.data.scenario, readiness.data.accounts, readiness.data.targets]
        .filter((chk) => !chk.ok)
        .map((chk) => chk.label)
    : [];

  return (
    <div className="flex flex-col gap-5 xl:grid xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start xl:gap-6">
      {/* ── Левая колонка: что именно запускаем ───────────────────────── */}
      <div className="flex min-w-0 flex-col gap-5">
        <Block title="Сценарий" action={
          <button
            onClick={onEditScenario}
            className="text-[13px] text-accent hover:underline"
          >
            Редактировать →
          </button>
        }>
          {scenario.data ? (
            <div className="rounded-card border border-status-active/50 bg-surface-1 p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="truncate text-[15px] font-semibold text-text-primary">
                  {scenario.data.name || `Сценарий ${scenario.data.id}`}
                </p>
                <span className="shrink-0 rounded-pill bg-status-active/15 px-2 py-0.5 text-[11px] font-medium text-status-active">
                  Кампания
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex -space-x-1.5">
                  {roleList.map((r, i) => (
                    <RoleAvatar key={r.id} name={r.name} color={roleColor(i)} size={22} />
                  ))}
                </div>
                <span className="text-[13px] text-text-tertiary">
                  {stepCount} {plural(stepCount, "реплика", "реплики", "реплик")}
                </span>
              </div>
            </div>
          ) : (
            <EmptyHint text="Сценарий ещё не создан — соберите роли и реплики на вкладке «Сценарий»." />
          )}
        </Block>

        <TargetsSection campaignId={campaignId} />

        <Block title="Пауза до первой реплики">
          <DualRange
            label="Ждём перед первым сообщением в новом чате"
            hint="Зайти в чат и сразу заговорить — самый заметный паттерн. Паузы ВНУТРИ диалога настраиваются отдельно."
            min={60}
            max={3600}
            step={30}
            valueMin={c.first_reply_delay_min_sec}
            valueMax={c.first_reply_delay_max_sec}
            disabled={patch.isPending}
            onChange={(lo, hi) =>
              patch.mutate({
                first_reply_delay_min_sec: lo,
                first_reply_delay_max_sec: hi,
              })
            }
          />
        </Block>

        <AccountsSection
          campaignId={campaignId}
          roles={roleList}
          personsNeeded={scenario.data?.persons_count ?? roleList.length}
        />
      </div>

      {/* ── Правая колонка: как именно это идёт ───────────────────────── */}
      <div className="flex min-w-0 flex-col gap-5">
        <Block
          title="Запуски"
          action={
            <button
              onClick={onOpenHistory}
              className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3 py-1.5 text-[12px] text-text-secondary active:text-text-primary"
            >
              <History className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              История
            </button>
          }
        >
          {problems.length > 0 ? (
            <div className="flex items-start gap-2 rounded-chip border-l-[3px] border-status-warning bg-surface-1 p-3">
              <AlertCircle
                className="mt-0.5 h-4 w-4 shrink-0 text-status-warning"
                strokeWidth={2}
                aria-hidden
              />
              <ul className="flex flex-col gap-0.5 text-[12px] text-text-secondary">
                {problems.map((p) => (
                  <li key={p}>• {p}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-[13px] text-status-active">
              Всё готово — можно запускать кнопкой внизу экрана.
            </p>
          )}
        </Block>

        <Block title="Параметры">
          <div className="flex flex-col gap-3">
            <ParamToggle
              label="Подхватывать ответы"
              hint="Если живой человек ответит реплаем на реплику бота, бот продолжит разговор. Окно задаётся ниже — после него тред считается старым и бот молчит."
              checked={c.auto_responder !== "off"}
              disabled={patch.isPending}
              onChange={(v) => patch.mutate({ auto_responder: v ? "reply_in_chat" : "off" })}
            >
              {c.auto_responder !== "off" && (
                <div className="mt-2 flex items-center gap-2">
                  <input
                    type="number"
                    min={1}
                    max={72}
                    value={c.pickup_replies_hours}
                    disabled={patch.isPending}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (v >= 1 && v <= 72) patch.mutate({ pickup_replies_hours: v });
                    }}
                    className="nums h-8 w-16 rounded-chip border border-hairline bg-surface-1 px-2 text-[13px] text-text-primary"
                  />
                  <span className="text-[12px] text-text-tertiary">ч после диалога</span>
                </div>
              )}
            </ParamToggle>

            <ParamToggle
              label="Уникализация"
              hint="Перед отправкой ИИ переписывает реплику своими словами — один и тот же сценарий в разных чатах не выглядит скопированным."
              checked={c.unique_messages}
              disabled={patch.isPending}
              onChange={(v) => patch.mutate({ unique_messages: v })}
            />

            <ParamToggle
              label="Проходить капчу"
              hint="Если в чате стоит бот-привратник, аккаунт пройдёт проверку сам. Иначе его сообщения удалят."
              checked={c.captcha_solver_enabled}
              disabled={patch.isPending}
              onChange={(v) => patch.mutate({ captcha_solver_enabled: v })}
            />

            <ParamToggle
              label="Реакции между аккаунтами"
              hint="Боты ставят эмодзи-реакции на реплики друг друга — живой разговор редко идёт совсем без реакций."
              checked={c.inter_account_reactions_enabled}
              disabled={patch.isPending}
              onChange={(v) => patch.mutate({ inter_account_reactions_enabled: v })}
            />

            <ParamToggle
              label="Менять состав между чатами"
              hint="Выключено: аккаунт играет одну и ту же роль во всех чатах — так диалог не разваливается, когда у учёток разные имя, пол и аватарка. Включите, если важнее не светить одну и ту же связку: Telegram банит связанные аккаунты пачкой. Закреплённые роли не меняются в любом случае."
              checked={c.shuffle_lineup_between_chats}
              disabled={patch.isPending}
              onChange={(v) => patch.mutate({ shuffle_lineup_between_chats: v })}
            />
          </div>
        </Block>

        <Block title="Темп">
          <div className="mb-1.5 text-[13px] text-text-secondary">Чаты идут</div>
          <div className="mb-2 flex gap-2">
            {[
              { v: 1, label: "По одному" },
              { v: 3, label: "До 3 сразу" },
            ].map(({ v, label }) => (
              <button
                key={v}
                type="button"
                disabled={patch.isPending}
                onClick={() => patch.mutate({ max_parallel_chats: v })}
                className={[
                  "flex-1 rounded-chip border px-3 py-2 text-[13px] font-medium transition-colors",
                  (c.max_parallel_chats > 1 ? 3 : 1) === v
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-hairline bg-surface-1 text-text-secondary",
                ].join(" ")}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mb-4 text-[11px] leading-snug text-text-tertiary">
            {c.max_parallel_chats > 1
              ? "До трёх диалогов одновременно — нужны свободные аккаунты на каждый. Быстрее, но заметнее."
              : "Следующий чат — после диалога в предыдущем и паузы ниже. Так естественнее: один и тот же разговор не всплывает в десяти чатах разом."}
          </p>

          <DualRange
            label="Пауза между чатами"
            hint="Случайная пауза перед следующим чатом."
            min={0}
            max={1800}
            step={30}
            valueMin={c.target_delay_min_sec}
            valueMax={c.target_delay_max_sec}
            disabled={patch.isPending}
            onChange={(lo, hi) =>
              patch.mutate({ target_delay_min_sec: lo, target_delay_max_sec: hi })
            }
          />

          {/* Колонка узкая (340px) — подпись и поле в одну строку не влезают
              и обрезаются, поэтому поле уходит на строку ниже. */}
          <div className="mt-4 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[13px] text-text-secondary">
                Медленный режим: ждать до
              </span>
              <HintDot text="В чатах со slow-mode Telegram заставляет ждать между сообщениями. Если ждать дольше этого лимита — пропускаем чат: сидеть 20 минут ради одной реплики бессмысленно." />
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <input
                type="number"
                min={0}
                max={60}
                value={Math.round(c.slow_mode_wait_max_sec / 60)}
                disabled={patch.isPending}
                onChange={(e) => {
                  const m = Number(e.target.value);
                  if (m >= 0 && m <= 60)
                    patch.mutate({ slow_mode_wait_max_sec: m * 60 });
                }}
                className="nums h-8 w-16 rounded-chip border border-hairline bg-surface-1 px-2 text-[13px] text-text-primary"
              />
              <span className="text-[12px] text-text-tertiary">мин</span>
            </div>
          </div>
        </Block>
      </div>
    </div>
  );
}

/* ── Цели: четыре режима ─────────────────────────────────────────────── */

function TargetsSection({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<TargetMode>("channel_monitor");
  const [text, setText] = useState("");

  const targets = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "targets"],
    queryFn: () => shillingApi.targets(campaignId),
    refetchInterval: (q) => {
      const data = q.state.data as Target[] | undefined;
      return data?.some((t) => t.status === "pending") ? 3000 : false;
    },
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "targets"] });

  const add = useMutation({
    mutationFn: (raws: string[]) => shillingApi.addTargets(campaignId, raws, mode),
    onSuccess: () => {
      setText("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (targetId: number) => shillingApi.removeTarget(campaignId, targetId),
    onSuccess: invalidate,
  });

  // Тумблер «мониторить всё, что на аккаунте» — флаг кампании. Когда включён,
  // ссылки вводить не нужно: софт сам соберёт каналы из подписок аккаунта.
  const campaign = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });
  const patchCampaign = useMutation({
    mutationFn: (body: { monitor_all_dialogs: boolean }) =>
      shillingApi.update(campaignId, body),
    onSuccess: (updated) => {
      qc.setQueryData(["shilling", "campaign", campaignId], updated);
      invalidate();
    },
  });
  const monitorAll = campaign.data?.monitor_all_dialogs ?? false;

  const lines = useMemo(() => splitLines(text), [text]);
  // Ссылки на посты считаем всегда: бэкенд делает из них channel_post
  // независимо от вкладки, и пользователь должен видеть, что его ввод
  // распознан именно так.
  const postLinks = useMemo(() => lines.filter((l) => POST_LINK_RE.test(l)).length, [lines]);

  const all: Target[] = targets.data ?? [];
  const current = all.filter((t) => t.mode === mode);
  const tab = MODE_TABS.find((t) => t.value === mode)!;

  return (
    <Block title={`Цели · ${all.length}`}>
      <div className="mb-3 flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
        {MODE_TABS.map((t) => {
          const count = all.filter((x) => x.mode === t.value).length;
          return (
            <button
              key={t.value}
              type="button"
              onClick={() => setMode(t.value)}
              className={[
                "shrink-0 rounded-chip px-3 py-1.5 text-[13px] font-medium transition-colors",
                mode === t.value
                  ? "bg-surface-2 text-text-primary"
                  : "text-text-secondary hover:text-text-primary",
              ].join(" ")}
            >
              {t.label}
              {count > 0 && <span className="ml-1 text-text-tertiary nums">{count}</span>}
            </button>
          );
        })}
      </div>

      <p className="mb-3 text-[12px] leading-snug text-text-tertiary">{tab.hint}</p>

      {mode === "channel_monitor" && (
        <div className="mb-3 rounded-chip border border-hairline bg-surface-1 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 text-[13px] text-text-primary">
              Мониторить всё, что на аккаунте
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={monitorAll}
              aria-label="Мониторить всё, что на аккаунте"
              disabled={patchCampaign.isPending}
              onClick={() => patchCampaign.mutate({ monitor_all_dialogs: !monitorAll })}
              className={[
                "relative inline-flex h-[26px] w-[44px] shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
                monitorAll ? "border-transparent bg-status-active" : "border-hairline bg-surface-2",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-[20px] w-[20px] rounded-full bg-white shadow-sm transition-transform duration-150",
                  monitorAll ? "translate-x-[21px]" : "translate-x-[2px]",
                ].join(" ")}
              />
            </button>
          </div>
          <p className="mt-1.5 text-[11px] leading-snug text-text-tertiary">
            {monitorAll
              ? "Ссылки вводить не нужно — софт сам собирает каналы из подписок аккаунта-парсера и следит за новыми постами. Они появятся ниже со значком «авто»."
              : "Включите, чтобы не перечислять каналы вручную: софт возьмёт их из подписок аккаунта."}
          </p>
        </div>
      )}

      {current.length > 0 ? (
        <div className="mb-3 flex flex-wrap gap-2">
          {current.map((t) => (
            <span
              key={t.id}
              className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 py-1 pl-2.5 pr-1.5 text-[13px]"
            >
              <span
                className={[
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  t.status === "resolved"
                    ? "bg-status-active"
                    : t.status === "error"
                      ? "bg-status-critical"
                      : "bg-status-neutral",
                ].join(" ")}
                aria-hidden
              />
              <span className="max-w-[180px] truncate text-text-primary">
                {t.title || t.raw_input}
                {t.post_id != null && (
                  <span className="text-text-tertiary nums">/{t.post_id}</span>
                )}
              </span>
              {t.auto_discovered ? (
                <span className="rounded-pill bg-surface-2 px-1.5 text-[10px] font-medium text-text-tertiary">
                  авто
                </span>
              ) : (
                <button
                  onClick={() => remove.mutate(t.id)}
                  aria-label="Удалить цель"
                  className="text-text-tertiary active:text-status-critical"
                >
                  <X className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
                </button>
              )}
            </span>
          ))}
        </div>
      ) : (
        <p className="mb-3 text-[13px] text-text-tertiary">
          {mode === "channel_monitor" && monitorAll
            ? "Каналы появятся здесь после ближайшей проверки подписок (каждые 5 минут)."
            : "В этом режиме целей пока нет."}
        </p>
      )}

      {!(mode === "channel_monitor" && monitorAll) && (
      <>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder={tab.placeholder}
        className="w-full resize-y rounded-chip border border-hairline bg-surface-1 px-4 py-3 font-mono text-[13px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
      />
      <div className="mt-2 flex items-center justify-between gap-3">
        <p className="text-[12px] text-text-tertiary">
          {mode === "channel_post" || postLinks > 0
            ? `Распознано постов: ${postLinks}`
            : `Строк: ${lines.length}`}
        </p>
        <button
          type="button"
          onClick={() => lines.length && add.mutate(lines)}
          disabled={!lines.length || add.isPending}
          className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-4 text-[13px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
        >
          <Plus className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          {add.isPending ? "Добавляем…" : "Добавить"}
        </button>
      </div>
      </>
      )}
    </Block>
  );
}

/* ── Аккаунты и роли ─────────────────────────────────────────────────── */

function AccountsSection({
  campaignId,
  roles,
  personsNeeded,
}: {
  campaignId: number;
  roles: Role[];
  personsNeeded: number;
}) {
  const qc = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);

  const links = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "accounts"],
    queryFn: () => shillingApi.accounts(campaignId),
  });
  const allAccounts = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => accountsApi.list(),
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "accounts"] });

  const attach = useMutation({
    mutationFn: (ids: number[]) =>
      Promise.all(ids.map((id) => shillingApi.attach(campaignId, { account_id: id }))),
    onSuccess: () => {
      setPickerOpen(false);
      invalidate();
    },
  });
  const detach = useMutation({
    mutationFn: (accountId: number) => shillingApi.detach(campaignId, accountId),
    onSuccess: invalidate,
  });
  const setRole = useMutation({
    mutationFn: (p: { accountId: number; role_id: number | null }) =>
      shillingApi.patchAccount(campaignId, p.accountId, { role_id: p.role_id }),
    onSuccess: invalidate,
  });

  const linkList: CampaignAccount[] = links.data ?? [];
  const primary = linkList.filter((l) => !l.is_reserve);
  const accById = new Map((allAccounts.data ?? []).map((a) => [a.id, a]));

  return (
    <>
      <Block
        title={`Аккаунты · ${primary.length}/${personsNeeded}`}
        action={
          <button
            onClick={() => setPickerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3 py-1.5 text-[12px] text-text-secondary active:text-text-primary"
          >
            <UserPlus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            Добавить
          </button>
        }
      >
        {primary.length === 0 ? (
          <EmptyHint text="Нет аккаунтов, готовых к работе. Нужно столько же, сколько ролей в сценарии." />
        ) : (
          <div className="flex flex-wrap gap-2">
            {primary.map((l) => {
              const acc = accById.get(l.account_id);
              return (
                <span
                  key={l.account_id}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 py-1 pl-2.5 pr-1.5 text-[13px] text-text-primary"
                >
                  {acc ? accountDisplay(acc) : `#${l.account_id}`}
                  <button
                    onClick={() => detach.mutate(l.account_id)}
                    aria-label="Убрать из кампании"
                    className="text-text-tertiary active:text-status-critical"
                  >
                    <X className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
                  </button>
                </span>
              );
            })}
          </div>
        )}
      </Block>

      <Block
        title="Роли и аккаунты"
        action={
          <HintDot text="«Любой из выбранных» — роль играет свободный аккаунт кампании. Если выбрать конкретный, он закрепляется за ролью и не меняется, даже когда включено «Менять состав между чатами»." />
        }
      >
        {roles.length === 0 ? (
          <EmptyHint text="В сценарии ещё нет ролей." />
        ) : (
          <div className="flex flex-col gap-2">
            {roles.map((r, i) => {
              const pinned = linkList.find((l) => l.role_id === r.id && !l.is_reserve);
              return (
                <div key={r.id} className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <RoleAvatar name={r.name} color={roleColor(i)} size={22} />
                    <span className="truncate text-[13px] text-text-primary">{r.name}</span>
                  </div>
                  <div className="w-[190px] shrink-0">
                    <Select
                      value={pinned ? String(pinned.account_id) : ""}
                      onChange={(v) => {
                        // Снимаем прежнее закрепление, иначе за ролью остались
                        // бы два аккаунта сразу.
                        if (pinned && String(pinned.account_id) !== v)
                          setRole.mutate({ accountId: pinned.account_id, role_id: null });
                        if (v) setRole.mutate({ accountId: Number(v), role_id: r.id });
                      }}
                      options={[
                        { value: "", label: "Любой из выбранных" },
                        ...primary.map((l) => ({
                          value: String(l.account_id),
                          label: accById.has(l.account_id)
                            ? accountDisplay(accById.get(l.account_id)!)
                            : `#${l.account_id}`,
                        })),
                      ]}
                    />
                  </div>
                </div>
              );
            })}
            {primary.length === 0 && (
              <p className="text-[12px] text-text-tertiary">Сначала добавьте аккаунты выше.</p>
            )}
          </div>
        )}
      </Block>

      <AccountPickerSheet
        open={pickerOpen}
        attachedIds={linkList.map((l) => l.account_id)}
        onDetach={(id) => detach.mutate(id)}
        busy={attach.isPending}
        onClose={() => setPickerOpen(false)}
        onAdd={(ids) => attach.mutate(ids)}
      />
    </>
  );
}

/* ── Мелкие блоки ────────────────────────────────────────────────────── */

function Block({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-[12px] font-semibold uppercase tracking-wider text-text-secondary">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function ParamToggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
  children,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-chip border border-hairline bg-surface-1 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-[13px] text-text-primary">{label}</span>
        <div className="flex shrink-0 items-center gap-2">
          <HintDot text={hint} />
          <button
            type="button"
            role="switch"
            aria-checked={checked}
            aria-label={label}
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className={[
              "relative inline-flex h-[26px] w-[44px] shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
              checked ? "border-transparent bg-status-active" : "border-hairline bg-surface-2",
            ].join(" ")}
          >
            <span
              className={[
                "inline-block h-[20px] w-[20px] rounded-full bg-white shadow-sm transition-transform duration-150",
                checked ? "translate-x-[21px]" : "translate-x-[2px]",
              ].join(" ")}
            />
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="rounded-chip border border-dashed border-hairline px-3 py-3 text-[13px] text-text-tertiary">
      {text}
    </p>
  );
}

const PALETTE = ["#f87171", "#fbbf24", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];
function roleColor(i: number): string {
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
