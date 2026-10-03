import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Filter, Link2, Play, UserCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { accountsApi } from "../../shared/accounts";
import { parsingApi } from "./api";
import { Checkbox } from "./components/Checkbox";

/* Экран запуска парсера. Никакого drawer-в-мастере — parsing это
   отдельный сервис (см. docs/priming-spec §8).

   Визуальный акцент (prompt от пользователя):
   - card--primary: главный блок (тип + ссылка) выделен тонкой
     --accent-полосой слева;
   - card--accent-dim: аккаунт-парсер — лёгкий status-active-фон как
     вторичный акцент;
   - sticky-футер прибит к контенту (не fixed), не перекрывает нав-бар. */

type Kind = "chat_messages" | "chat_members";

export function RunParsingScreen() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("chat_messages");
  const [chatRef, setChatRef] = useState("");
  const [collectorId, setCollectorId] = useState<number | null>(null);
  const [daysWindow, setDaysWindow] = useState(14);
  const [minMessages, setMinMessages] = useState(2);
  const [onlyRecentlySeen, setOnlyRecentlySeen] = useState(true);
  const [requireUsername, setRequireUsername] = useState(true);
  const [premiumOnly, setPremiumOnly] = useState(false);

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
      const base = {
        name: name.trim(),
        collector_account_id: collectorId,
        chat_ref: chatRef.trim(),
        require_username: requireUsername,
        premium_only: premiumOnly,
      };
      if (kind === "chat_messages") {
        return parsingApi.runChatMessages({
          ...base, days_window: daysWindow, min_messages: minMessages,
        });
      }
      return parsingApi.runChatMembers({
        ...base, only_recently_seen: onlyRecentlySeen,
      });
    },
    onSuccess: () => navigate("/modules/parsing"),
  });

  const problems: string[] = [];
  if (!name.trim()) problems.push("Укажите имя списка");
  if (!chatRef.trim()) problems.push("Укажите @username или ссылку на чат");
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
        {/* Имя списка — вспомогательное поле */}
        <div className="card p-5">
          <label className="block text-[13px] font-medium text-text-secondary">
            Имя списка
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="AI news · участники · 14 дней"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </div>

        {/* Главный блок: тип + источник. Акцент — левая полоса. */}
        <div className="card relative overflow-hidden p-5">
          <span
            className="absolute inset-y-0 left-0 w-[3px] bg-accent"
            aria-hidden
          />
          <div className="mb-3 flex items-center gap-2">
            <Link2
              className="h-4 w-4 text-accent"
              strokeWidth={2.2}
              aria-hidden
            />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">
              Источник
            </div>
          </div>

          <div className="flex gap-2">
            {(["chat_messages", "chat_members"] as Kind[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={[
                  "flex-1 rounded-pill px-3.5 py-2 text-[13px] font-medium transition-colors border",
                  kind === k
                    ? "bg-surface-2 border-strong text-text-primary"
                    : "bg-surface-1 border-hairline text-text-secondary",
                ].join(" ")}
              >
                {k === "chat_messages" ? "Активные в чате" : "Все участники"}
              </button>
            ))}
          </div>

          <label className="mt-4 block text-[13px] font-medium text-text-secondary">
            Ссылка на чат
          </label>
          <input
            value={chatRef}
            onChange={(e) => setChatRef(e.target.value)}
            placeholder="@ainews или t.me/…"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />

          {kind === "chat_messages" && (
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="text-[13px] font-medium text-text-secondary">
                Окно, дней
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={daysWindow}
                  onChange={(e) => setDaysWindow(Number(e.target.value))}
                  className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary"
                />
              </label>
              <label className="text-[13px] font-medium text-text-secondary">
                Мин. сообщений
                <input
                  type="number"
                  min={1}
                  value={minMessages}
                  onChange={(e) => setMinMessages(Number(e.target.value))}
                  className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary"
                />
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

        {/* Collector — второй по важности, подсветка status-active */}
        <div className="card relative overflow-hidden p-5">
          <span
            className="absolute inset-y-0 left-0 w-[3px] bg-status-active opacity-80"
            aria-hidden
          />
          <div className="mb-2 flex items-center gap-2">
            <UserCheck
              className="h-4 w-4 text-status-active"
              strokeWidth={2.2}
              aria-hidden
            />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">
              Аккаунт-парсер
            </div>
          </div>
          <p className="mb-3 text-[12px] text-text-tertiary">
            Не должен совпадать с прайминг-аккаунтом. Безопасно отделяет
            чтение от праймов.
          </p>
          <div className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
            {collectors.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setCollectorId(a.id)}
                className={[
                  "flex items-center justify-between rounded-xl border p-3 text-left transition-colors",
                  collectorId === a.id
                    ? "border-strong bg-surface-2"
                    : "border-hairline bg-surface-1 active:bg-surface-2",
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
              <p className="text-[13px] text-text-tertiary">
                Нет свободных аккаунтов в пуле.
              </p>
            )}
          </div>
        </div>

        {/* Фильтры */}
        <div className="card p-5">
          <div className="mb-2 flex items-center gap-2">
            <Filter
              className="h-4 w-4 text-text-secondary"
              strokeWidth={2}
              aria-hidden
            />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">
              Фильтры
            </div>
          </div>
          <Checkbox
            checked={requireUsername}
            onChange={setRequireUsername}
            label="Только с @username"
          />
          <Checkbox
            checked={premiumOnly}
            onChange={setPremiumOnly}
            label="Только Telegram Premium"
          />
        </div>

        {/* Sticky action bar — внутри потока блоков, не fixed */}
        <div
          className="sticky bottom-0 z-10 -mx-4 mt-2 border-t border-hairline bg-bg-elevated/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border"
          style={{
            paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)",
          }}
        >
          {problems.length > 0 && (
            <div className="mb-2 flex items-start gap-2 rounded-xl border-l-[4px] border-status-warning bg-surface-1 p-3">
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
          <button
            type="button"
            disabled={problems.length > 0 || submit.isPending}
            onClick={() => submit.mutate()}
            className={[
              "inline-flex h-11 w-full items-center justify-center gap-2 rounded-pill text-[15px] font-semibold transition-opacity",
              problems.length === 0
                ? "bg-accent text-accent-on active:opacity-80"
                : "bg-surface-2 text-text-tertiary",
            ].join(" ")}
          >
            {submit.isPending ? "Запуск…" : (
              <>
                <Play className="h-4 w-4" strokeWidth={2.4} aria-hidden />
                Запустить парсинг
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
