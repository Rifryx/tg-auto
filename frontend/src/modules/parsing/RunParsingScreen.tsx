import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Filter, Link2, Play, UserCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { accountsApi } from "../../shared/accounts";
import { parsingApi } from "./api";
import type { AudienceFilters } from "./types";
import { Checkbox } from "./components/Checkbox";

/* Экран запуска парсера (Extraction+, этап 1): 4 источника аудитории +
   расширенные фильтры профиля/активности. */

type Kind = "chat_messages" | "chat_members" | "channel_commenters" | "post_reactors";

const KINDS: { value: Kind; label: string }[] = [
  { value: "chat_messages", label: "Активные в чате" },
  { value: "chat_members", label: "Все участники" },
  { value: "channel_commenters", label: "Комментаторы канала" },
  { value: "post_reactors", label: "Реакторы постов" },
];

const USES_WINDOW = new Set<Kind>(["chat_messages", "channel_commenters"]);

const inputCls =
  "mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary";

export function RunParsingScreen() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("chat_messages");
  const [chatRef, setChatRef] = useState("");
  const [collectorId, setCollectorId] = useState<number | null>(null);
  // messages / commenters
  const [daysWindow, setDaysWindow] = useState(14);
  const [minMessages, setMinMessages] = useState(2);
  // members
  const [onlyRecentlySeen, setOnlyRecentlySeen] = useState(true);
  // reactors
  const [postsLimit, setPostsLimit] = useState(20);
  const [reactionsPerPost, setReactionsPerPost] = useState(100);
  const [minReactions, setMinReactions] = useState(1);
  // filters
  const [requireUsername, setRequireUsername] = useState(true);
  const [premiumOnly, setPremiumOnly] = useState(false);
  const [requirePhoto, setRequirePhoto] = useState(false);
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [excludeScamFake, setExcludeScamFake] = useState(true);
  const [requirePhoneVisible, setRequirePhoneVisible] = useState(false);
  const [usernameRegex, setUsernameRegex] = useState("");
  const [nameScript, setNameScript] = useState<"" | "cyrillic" | "latin">("");
  const [lastSeenMaxDays, setLastSeenMaxDays] = useState("");

  const accountsQuery = useQuery({
    queryKey: ["accounts", "pool"],
    queryFn: () => accountsApi.list(),
  });
  const collectors = useMemo(
    () => (accountsQuery.data ?? []).filter((a) => a.status === "pool"),
    [accountsQuery.data],
  );

  const submit = useMutation({
    mutationFn: async () => {
      if (!collectorId) throw new Error("no collector");
      const filters: AudienceFilters = {
        require_username: requireUsername,
        premium_only: premiumOnly,
        require_photo: requirePhoto,
        verified_only: verifiedOnly,
        exclude_scam_fake: excludeScamFake,
        require_phone_visible: requirePhoneVisible,
        username_regex: usernameRegex.trim() || null,
        name_script: nameScript || null,
        last_seen_max_days: lastSeenMaxDays === "" ? null : Number(lastSeenMaxDays),
      };
      const base = { name: name.trim(), collector_account_id: collectorId, chat_ref: chatRef.trim(), ...filters };
      if (kind === "chat_messages")
        return parsingApi.runChatMessages({ ...base, days_window: daysWindow, min_messages: minMessages });
      if (kind === "channel_commenters")
        return parsingApi.runChannelCommenters({ ...base, days_window: daysWindow, min_messages: minMessages });
      if (kind === "post_reactors")
        return parsingApi.runPostReactors({
          ...base, posts_limit: postsLimit, reactions_per_post: reactionsPerPost, min_reactions: minReactions,
        });
      return parsingApi.runChatMembers({ ...base, only_recently_seen: onlyRecentlySeen });
    },
    onSuccess: () => navigate("/modules/parsing"),
  });

  const problems: string[] = [];
  if (!name.trim()) problems.push("Укажите имя списка");
  if (!chatRef.trim())
    problems.push(
      kind === "post_reactors" || kind === "channel_commenters"
        ? "Укажите @username или ссылку на канал"
        : "Укажите @username или ссылку на чат",
    );
  if (!collectorId) problems.push("Выберите аккаунт-парсер (collector)");

  return (
    <div className="min-h-full">
      <ScreenHeader
        title="Запуск парсинга"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/parsing")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К спискам
          </button>
        }
      />

      <div className="flex flex-col gap-4">
        <div className="card p-5">
          <label className="block text-[13px] font-medium text-text-secondary">Имя списка</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="AI news · комментаторы · 14 дней"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </div>

        <div className="card relative overflow-hidden p-5">
          <span className="absolute inset-y-0 left-0 w-[3px] bg-accent" aria-hidden />
          <div className="mb-3 flex items-center gap-2">
            <Link2 className="h-4 w-4 text-accent" strokeWidth={2.2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">Источник</div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {KINDS.map((k) => (
              <button
                key={k.value}
                type="button"
                onClick={() => setKind(k.value)}
                className={[
                  "rounded-pill px-3.5 py-2 text-[13px] font-medium transition-colors border",
                  kind === k.value
                    ? "bg-surface-2 border-strong text-text-primary"
                    : "bg-surface-1 border-hairline text-text-secondary",
                ].join(" ")}
              >
                {k.label}
              </button>
            ))}
          </div>

          <label className="mt-4 block text-[13px] font-medium text-text-secondary">
            {kind === "post_reactors" || kind === "channel_commenters" ? "Ссылка на канал" : "Ссылка на чат"}
          </label>
          <input
            value={chatRef}
            onChange={(e) => setChatRef(e.target.value)}
            placeholder="@ainews или t.me/…"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />

          {USES_WINDOW.has(kind) && (
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="text-[13px] font-medium text-text-secondary">
                Окно, дней
                <input type="number" min={1} max={60} value={daysWindow}
                  onChange={(e) => setDaysWindow(Number(e.target.value))} className={inputCls} />
              </label>
              <label className="text-[13px] font-medium text-text-secondary">
                Мин. сообщений
                <input type="number" min={1} value={minMessages}
                  onChange={(e) => setMinMessages(Number(e.target.value))} className={inputCls} />
              </label>
            </div>
          )}

          {kind === "post_reactors" && (
            <div className="mt-4 grid grid-cols-3 gap-3">
              <label className="text-[13px] font-medium text-text-secondary">
                Постов
                <input type="number" min={1} max={200} value={postsLimit}
                  onChange={(e) => setPostsLimit(Number(e.target.value))} className={inputCls} />
              </label>
              <label className="text-[13px] font-medium text-text-secondary">
                Реакций/пост
                <input type="number" min={1} max={100} value={reactionsPerPost}
                  onChange={(e) => setReactionsPerPost(Number(e.target.value))} className={inputCls} />
              </label>
              <label className="text-[13px] font-medium text-text-secondary">
                Мин. реакций
                <input type="number" min={1} value={minReactions}
                  onChange={(e) => setMinReactions(Number(e.target.value))} className={inputCls} />
              </label>
            </div>
          )}

          {kind === "chat_members" && (
            <div className="mt-4">
              <Checkbox
                checked={onlyRecentlySeen}
                onChange={setOnlyRecentlySeen}
                label="Только «был недавно»"
                description="Активные за последние ~7 дней по user.status."
              />
            </div>
          )}
        </div>

        <div className="card relative overflow-hidden p-5">
          <span className="absolute inset-y-0 left-0 w-[3px] bg-status-active opacity-80" aria-hidden />
          <div className="mb-2 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-status-active" strokeWidth={2.2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">Аккаунт-парсер</div>
          </div>
          <p className="mb-3 text-[12px] text-text-tertiary">
            Отдельный от рабочих аккаунт для чтения.
          </p>
          <div className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
            {collectors.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setCollectorId(a.id)}
                className={[
                  "flex items-center justify-between rounded-xl border p-3 text-left transition-colors",
                  collectorId === a.id ? "border-strong bg-surface-2" : "border-hairline bg-surface-1 active:bg-surface-2",
                ].join(" ")}
              >
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-medium text-text-primary">
                    {a.username ? `@${a.username}` : a.phone}
                  </div>
                </div>
                {collectorId === a.id && (
                  <span className="rounded-pill bg-status-active/15 px-2 py-0.5 text-[10px] uppercase tracking-wider text-status-active">
                    выбран
                  </span>
                )}
              </button>
            ))}
            {collectors.length === 0 && (
              <p className="text-[13px] text-text-tertiary">Нет свободных аккаунтов в пуле.</p>
            )}
          </div>
        </div>

        <div className="card p-5">
          <div className="mb-3 flex items-center gap-2">
            <Filter className="h-4 w-4 text-text-secondary" strokeWidth={2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">Фильтры</div>
          </div>
          <Checkbox checked={requireUsername} onChange={setRequireUsername} label="Только с @username" />
          <Checkbox checked={premiumOnly} onChange={setPremiumOnly} label="Только Telegram Premium" />
          <Checkbox checked={requirePhoto} onChange={setRequirePhoto} label="Только с аватаркой" />
          <Checkbox checked={verifiedOnly} onChange={setVerifiedOnly} label="Только verified" />
          <Checkbox
            checked={excludeScamFake}
            onChange={setExcludeScamFake}
            label="Исключать scam/fake"
            description="Помеченные Telegram как мошеннические/поддельные."
          />
          <Checkbox
            checked={requirePhoneVisible}
            onChange={setRequirePhoneVisible}
            label="Только с видимым телефоном"
          />

          <label className="mt-3 block text-[13px] font-medium text-text-secondary">
            Имя (алфавит)
          </label>
          <div className="mt-1 flex gap-2">
            {([["", "Любой"], ["cyrillic", "Кириллица"], ["latin", "Латиница"]] as const).map(([v, lbl]) => (
              <button
                key={v}
                type="button"
                onClick={() => setNameScript(v)}
                className={[
                  "flex-1 rounded-pill border px-3 py-1.5 text-[13px] font-medium",
                  nameScript === v ? "border-strong bg-surface-2 text-text-primary" : "border-hairline bg-surface-1 text-text-secondary",
                ].join(" ")}
              >
                {lbl}
              </button>
            ))}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="text-[13px] font-medium text-text-secondary">
              Онлайн ≤ дней
              <input
                type="number" min={0} value={lastSeenMaxDays}
                onChange={(e) => setLastSeenMaxDays(e.target.value.replace(/\D/g, ""))}
                placeholder="любой" className={inputCls}
              />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">
              Username regex
              <input
                value={usernameRegex}
                onChange={(e) => setUsernameRegex(e.target.value)}
                placeholder="^crypto"
                className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 font-mono text-[13px] text-text-primary"
              />
            </label>
          </div>
        </div>

        <div
          className="sticky bottom-0 z-10 -mx-4 mt-2 border-t border-hairline bg-bg-elevated/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
        >
          {problems.length > 0 && (
            <div className="mb-2 flex items-start gap-2 rounded-xl border-l-[4px] border-status-warning bg-surface-1 p-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" strokeWidth={2} aria-hidden />
              <ul className="text-[13px] text-text-secondary">
                {problems.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
          <button
            type="button"
            disabled={problems.length > 0 || submit.isPending}
            onClick={() => submit.mutate()}
            className={[
              "inline-flex h-11 w-full items-center justify-center gap-2 rounded-pill text-[15px] font-semibold transition-opacity",
              problems.length === 0 ? "bg-accent text-accent-on active:opacity-80" : "bg-surface-2 text-text-tertiary",
            ].join(" ")}
          >
            {submit.isPending ? "Запуск…" : (<><Play className="h-4 w-4" strokeWidth={2.4} aria-hidden />Запустить парсинг</>)}
          </button>
        </div>
      </div>
    </div>
  );
}
