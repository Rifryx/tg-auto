import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { accountsApi } from "../../shared/accounts";
import type { Account } from "../../shared/types";
import { primingApi } from "./api";
import { PillGroup } from "./components/PillGroup";
import { PushPreview } from "./components/PushPreview";
import { Section } from "./components/Section";
import { Stepper } from "./components/Stepper";
import type {
  HumanizerMode,
  PrimingTriggerAction,
  WarmupProfile,
} from "./types";

/* Мастер новой кампании (docs/priming-ui.md §5.1-5.7). Один вертикальный
   скролл, секции-карточки, sticky footer с сводкой и CTA. */

const TRIGGER_OPTIONS: { key: PrimingTriggerAction; label: string; note: string }[] = [
  {
    key: "secret_chat_request",
    label: "Секретный чат",
    note: "«{{name}} пригласил вас в секретный чат» — самый чистый push",
  },
  {
    key: "set_ttl_1d",
    label: "Автоудаление (24 ч)",
    note: "«{{name}} включил автоудаление сообщений»",
  },
  {
    key: "contact_added",
    label: "Добавление в контакты",
    note: "«{{name}} добавил вас в контакты» — требует username/phone",
  },
];

const HUMANIZER_OPTIONS: { key: HumanizerMode; label: string }[] = [
  { key: "off", label: "Off" },
  { key: "balanced", label: "Balanced" },
  { key: "aggressive", label: "Aggressive" },
];

const WARMUP_OPTIONS: { key: WarmupProfile; label: string }[] = [
  { key: "cold", label: "Cold · 5/день" },
  { key: "warm", label: "Warm · 20/день" },
  { key: "hot", label: "Hot · 40/день" },
];

const WARMUP_DEFAULTS: Record<
  WarmupProfile,
  { limit: number; min: number; max: number }
> = {
  cold: { limit: 5, min: 200, max: 600 },
  warm: { limit: 20, min: 60, max: 200 },
  hot: { limit: 40, min: 20, max: 60 },
};

// ─────────────────────────────────────────────────────────────────────────

export function NewPrimingScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  // Форма
  const [name, setName] = useState("");
  const [action, setAction] = useState<PrimingTriggerAction>("secret_chat_request");
  const [warmup, setWarmup] = useState<WarmupProfile>("warm");
  const [dailyLimit, setDailyLimit] = useState(20);
  const [delayMin, setDelayMin] = useState(60);
  const [delayMax, setDelayMax] = useState(200);
  const [humanizer, setHumanizer] = useState<HumanizerMode>("balanced");
  const [dryRun, setDryRun] = useState(false);

  const [pickedAccounts, setPickedAccounts] = useState<Set<number>>(new Set());
  const [manualList, setManualList] = useState("");
  const [csvName, setCsvName] = useState<string | null>(null);
  const [csvRows, setCsvRows] = useState<
    { tg_user_id?: number; username?: string; phone?: string }[]
  >([]);
  const [audienceTab, setAudienceTab] = useState<"manual" | "csv">("manual");

  // Меняем warmup — подставляем дефолты, если пользователь не правил.
  function applyWarmup(p: WarmupProfile) {
    setWarmup(p);
    const d = WARMUP_DEFAULTS[p];
    setDailyLimit(d.limit);
    setDelayMin(d.min);
    setDelayMax(d.max);
  }

  // Аккаунты пула
  const accountsQuery = useQuery({
    queryKey: ["accounts", "pool"],
    queryFn: () => accountsApi.list(),
  });
  const availableAccounts = useMemo(
    () => (accountsQuery.data ?? []).filter((a) => a.status === "pool"),
    [accountsQuery.data],
  );

  // Парсинг вручную-списка
  const manualTargets = useMemo(() => parseManualList(manualList), [manualList]);
  const targets = audienceTab === "csv" ? csvRows : manualTargets;

  // Валидация
  const problems: string[] = [];
  if (!name.trim()) problems.push("Укажите имя кампании");
  if (pickedAccounts.size === 0) problems.push("Выберите хотя бы один аккаунт");
  if (targets.length === 0) problems.push("Добавьте хотя бы одну цель");
  if (delayMin > delayMax) problems.push("Минимальная задержка больше максимальной");

  // Запуск
  const submit = useMutation({
    mutationFn: async () => {
      const created = await primingApi.create({
        name: name.trim(),
        trigger_action: action,
        humanizer_mode: humanizer,
        warmup_profile: warmup,
        daily_limit_per_account: dailyLimit,
        delay_between_targets_sec_min: delayMin,
        delay_between_targets_sec_max: delayMax,
        dry_run: dryRun,
      });
      await primingApi.attachAccounts(created.id, Array.from(pickedAccounts));
      await primingApi.importTargets(created.id, targets);
      const started = await primingApi.start(created.id);
      return started.id;
    },
    onSuccess: (id) => {
      qc.invalidateQueries({ queryKey: ["priming", "campaigns"] });
      navigate(`/modules/priming/campaigns/${id}`);
    },
  });

  const canSubmit = problems.length === 0 && !submit.isPending;

  return (
    <div className="min-h-full pb-40">
      <ScreenHeader
        title="Новая кампания"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/priming")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К списку
          </button>
        }
      />

      <div className="flex flex-col gap-6">
        {/* Идентификация */}
        <Section title="Идентификация">
          <label className="block text-[13px] font-medium text-text-secondary">
            Имя кампании
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например: Запуск по чату «AI news RU»"
            maxLength={120}
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </Section>

        {/* §5.1 Триггер + preview */}
        <Section
          title="Что увидит цель в уведомлении"
          description="Push реально приходит у большинства клиентов — конкретные проценты уточняем в R&D."
        >
          <div className="flex flex-col gap-2.5">
            {TRIGGER_OPTIONS.map(({ key, label, note }) => {
              const active = action === key;
              return (
                <button
                  type="button"
                  key={key}
                  onClick={() => setAction(key)}
                  className={[
                    "flex items-start gap-3 rounded-2xl border p-3.5 text-left transition-colors",
                    active
                      ? "border-strong bg-surface-2"
                      : "border-hairline bg-surface-1 active:bg-surface-2",
                  ].join(" ")}
                >
                  <span
                    className={[
                      "mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                      active ? "border-text-primary" : "border-strong",
                    ].join(" ")}
                    aria-hidden
                  >
                    {active && <span className="h-2 w-2 rounded-full bg-text-primary" />}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[15px] font-medium text-text-primary">{label}</div>
                    <div className="mt-0.5 text-[12px] text-text-tertiary">{note}</div>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-4">
            <PushPreview action={action} />
          </div>
        </Section>

        {/* §5.2 Аккаунты */}
        <Section
          title={`Аккаунты · ${pickedAccounts.size} выбрано`}
          description="Только аккаунты в статусе pool. Работать одновременно с двумя кампаниями один аккаунт не сможет."
        >
          {accountsQuery.isLoading && (
            <div className="h-16 animate-pulse rounded-2xl bg-surface-2" />
          )}
          {availableAccounts.length === 0 && !accountsQuery.isLoading && (
            <p className="text-[13px] text-text-secondary">
              Нет аккаунтов в пуле. Добавьте или прогрейте сначала.
            </p>
          )}
          <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
            {availableAccounts.map((a) => (
              <AccountRow
                key={a.id}
                account={a}
                selected={pickedAccounts.has(a.id)}
                onToggle={() => {
                  const next = new Set(pickedAccounts);
                  if (next.has(a.id)) next.delete(a.id);
                  else next.add(a.id);
                  setPickedAccounts(next);
                }}
              />
            ))}
          </div>
        </Section>

        {/* §5.3 Аудитория (без drawer-парсера — 3.3) */}
        <Section
          title="Аудитория"
          description="Кого праймить. Парсер чата приезжает следующим промптом."
        >
          <div className="mb-3">
            <PillGroup
              value={audienceTab}
              options={[
                { key: "manual", label: "Ручной список" },
                { key: "csv", label: "Импорт CSV" },
              ]}
              onChange={(v) => setAudienceTab(v)}
              fullWidth
            />
          </div>

          {audienceTab === "manual" && (
            <>
              <textarea
                value={manualList}
                onChange={(e) => setManualList(e.target.value)}
                placeholder={
                  "Один @username или phone на строку\n@alice\n+79001234567\n123456789"
                }
                rows={6}
                className="w-full resize-y rounded-xl border border-hairline bg-surface-2 p-3 font-mono text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
              />
              <p className="mt-2 text-[12px] text-text-tertiary">
                Найдено целей: <span className="tabular-nums text-text-primary">
                  {manualTargets.length}
                </span>
              </p>
            </>
          )}

          {audienceTab === "csv" && (
            <div className="flex flex-col gap-2">
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-2xl border border-dashed border-strong bg-surface-1 p-6 text-[14px] text-text-secondary hover:text-text-primary">
                <Upload className="h-4 w-4" strokeWidth={2} aria-hidden />
                <span>Выберите CSV (tg_user_id / username / phone)</span>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    setCsvName(f.name);
                    setCsvRows(await parseCsvFile(f));
                  }}
                />
              </label>
              {csvName && (
                <p className="text-[12px] text-text-tertiary">
                  {csvName} · строк: <span className="tabular-nums text-text-primary">
                    {csvRows.length}
                  </span>
                </p>
              )}
            </div>
          )}
        </Section>

        {/* §5.4 Профиль-пресет — заглушка до промпта 4.4 */}
        <Section
          title="Профиль-пресет (POC)"
          description="Оформление профиля под конверсию. Полный редактор — на этапе 4."
        >
          <div className="rounded-2xl border border-dashed border-strong bg-surface-1 p-4 text-[13px] text-text-secondary">
            Пока используется профиль аккаунта как есть.
            <br />
            Anchor-канал, stories и bio-редактор — на этапе 4 (см. docs/priming-ui.md §8).
          </div>
        </Section>

        {/* §5.5 Темп и лимиты */}
        <Section title="Темп и лимиты">
          <div className="mb-4">
            <div className="mb-2 text-[13px] font-medium text-text-secondary">
              Профиль прогрева
            </div>
            <PillGroup
              value={warmup}
              options={WARMUP_OPTIONS}
              onChange={applyWarmup}
              fullWidth
            />
          </div>

          <div className="grid grid-cols-1 gap-4 rounded-2xl bg-surface-2 p-4 sm:grid-cols-2">
            <Stepper
              label="Дневной лимит на аккаунт"
              value={dailyLimit}
              onChange={setDailyLimit}
              min={1}
              max={500}
            />
            <Stepper
              label="Минимальная задержка"
              value={delayMin}
              onChange={setDelayMin}
              min={0}
              max={delayMax}
              step={10}
              unit="с"
            />
            <Stepper
              label="Максимальная задержка"
              value={delayMax}
              onChange={setDelayMax}
              min={delayMin}
              max={3600}
              step={10}
              unit="с"
            />
          </div>
        </Section>

        {/* §5.6 Humanizer */}
        <Section
          title="Humanizer"
          description="Фоновая имитация активности в паузах между праймами."
        >
          <PillGroup
            value={humanizer}
            options={HUMANIZER_OPTIONS}
            onChange={setHumanizer}
            fullWidth
          />
        </Section>

        {/* dry-run toggle */}
        <Section
          title="Тестовый прогон"
          description="Симуляция outcome по распределению без реальных Push. Полезно для UI/E2E."
        >
          <label className="flex cursor-pointer items-center justify-between gap-3">
            <span className="text-[15px] text-text-primary">dry-run</span>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="h-5 w-5 accent-text-primary"
            />
          </label>
        </Section>
      </div>

      {/* §5.7 Sticky footer */}
      <div
        className="fixed inset-x-0 bottom-0 z-30 mx-auto border-t border-hairline bg-bg-elevated/95 px-4 pt-3 pb-4 backdrop-blur"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
      >
        <div className="mx-auto flex max-w-2xl flex-col gap-2">
          {problems.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl border-l-[4px] border-status-warning bg-surface-1 p-3">
              <AlertCircle
                className="mt-0.5 h-4 w-4 shrink-0 text-status-warning"
                strokeWidth={2}
                aria-hidden
              />
              <ul className="text-[13px] text-text-secondary">
                {problems.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {submit.isError && (
            <p className="text-[13px] text-status-critical">
              Не удалось запустить кампанию. Проверьте лимиты и повторите.
            </p>
          )}
          <div className="flex items-center justify-between gap-3">
            <div className="text-[13px] text-text-secondary">
              <span className="tabular-nums text-text-primary">{pickedAccounts.size}</span> акк ·{" "}
              <span className="tabular-nums text-text-primary">{targets.length}</span> целей
            </div>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() => submit.mutate()}
              className={[
                "inline-flex h-11 min-w-[220px] items-center justify-center gap-2 rounded-pill px-5 text-[15px] font-semibold transition-opacity",
                canSubmit
                  ? "bg-accent text-accent-on active:opacity-80"
                  : "bg-surface-2 text-text-tertiary",
              ].join(" ")}
            >
              {submit.isPending ? (
                "Запуск…"
              ) : (
                <>
                  <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                  Проверить и запустить
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────

function AccountRow({
  account,
  selected,
  onToggle,
}: {
  account: Account;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={[
        "flex items-center justify-between gap-3 rounded-xl border p-3 text-left transition-colors",
        selected
          ? "border-strong bg-surface-2"
          : "border-hairline bg-surface-1 active:bg-surface-2",
      ].join(" ")}
    >
      <div className="min-w-0">
        <div className="truncate text-[14px] font-medium text-text-primary">
          {account.username ? `@${account.username}` : account.phone}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-text-tertiary">
          {account.first_name || "—"}
          {account.last_name ? ` ${account.last_name}` : ""}
        </div>
      </div>
      <span
        className={[
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border",
          selected ? "border-text-primary bg-text-primary" : "border-strong",
        ].join(" ")}
        aria-hidden
      >
        {selected && <Check className="h-3.5 w-3.5 text-accent-on" strokeWidth={2.5} />}
      </span>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────

function parseManualList(text: string): {
  tg_user_id?: number;
  username?: string;
  phone?: string;
}[] {
  const out: { tg_user_id?: number; username?: string; phone?: string }[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    let row: { tg_user_id?: number; username?: string; phone?: string };
    if (line.startsWith("@")) {
      row = { username: line.slice(1) };
    } else if (line.startsWith("+")) {
      row = { phone: line.replace(/\s+/g, "") };
    } else if (/^\d+$/.test(line)) {
      row = { tg_user_id: Number(line) };
    } else {
      row = { username: line };
    }
    const key = JSON.stringify(row);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

async function parseCsvFile(file: File): Promise<
  { tg_user_id?: number; username?: string; phone?: string }[]
> {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length === 0) return [];
  const header = lines[0].split(",").map((s) => s.trim().toLowerCase());
  const rows: { tg_user_id?: number; username?: string; phone?: string }[] = [];
  for (const line of lines.slice(1)) {
    const cells = line.split(",");
    const record: Record<string, string> = {};
    header.forEach((h, i) => {
      record[h] = (cells[i] ?? "").trim();
    });
    const row: { tg_user_id?: number; username?: string; phone?: string } = {};
    if (record.tg_user_id) {
      const n = Number(record.tg_user_id);
      if (Number.isFinite(n) && n > 0) row.tg_user_id = n;
    }
    if (record.username) row.username = record.username.replace(/^@/, "");
    if (record.phone) row.phone = record.phone.replace(/\s+/g, "");
    if (row.tg_user_id || row.username || row.phone) rows.push(row);
  }
  return rows;
}
