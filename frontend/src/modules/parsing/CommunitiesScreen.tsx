import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Filter, Link2, Play, UserCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { accountsApi } from "../../shared/accounts";
import { parsingApi } from "./api";
import { Checkbox } from "./components/Checkbox";

/* Discovery сообществ (этап 2): вставить ссылки на каналы/чаты → collector
   обогащает каждую (участники, linked-чат, последний пост, флаги) и фильтрует. */

const inputCls =
  "mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary";

export function CommunitiesScreen() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [refsText, setRefsText] = useState("");
  const [collectorId, setCollectorId] = useState<number | null>(null);
  const [kind, setKind] = useState<"" | "channel" | "chat">("");
  const [minP, setMinP] = useState("");
  const [maxP, setMaxP] = useState("");
  const [requirePublic, setRequirePublic] = useState(false);
  const [requireLinked, setRequireLinked] = useState(false);
  const [lastPostMaxDays, setLastPostMaxDays] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [excludeScamFake, setExcludeScamFake] = useState(true);
  const [titleRegex, setTitleRegex] = useState("");
  const [usernameRegex, setUsernameRegex] = useState("");

  const accountsQuery = useQuery({ queryKey: ["accounts", "pool"], queryFn: () => accountsApi.list() });
  const collectors = useMemo(
    () => (accountsQuery.data ?? []).filter((a) => a.status === "pool"),
    [accountsQuery.data],
  );

  const refs = useMemo(
    () => refsText.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean),
    [refsText],
  );

  const submit = useMutation({
    mutationFn: () => {
      if (!collectorId) throw new Error("no collector");
      return parsingApi.runCommunities({
        name: name.trim(),
        collector_account_id: collectorId,
        refs,
        kind: kind || null,
        min_participants: minP ? Number(minP) : null,
        max_participants: maxP ? Number(maxP) : null,
        require_public: requirePublic,
        require_linked_chat: requireLinked,
        last_post_max_days: lastPostMaxDays ? Number(lastPostMaxDays) : null,
        verified_only: verifiedOnly,
        exclude_scam_fake: excludeScamFake,
        title_regex: titleRegex.trim() || null,
        username_regex: usernameRegex.trim() || null,
      });
    },
    onSuccess: () => navigate("/modules/parsing"),
  });

  const problems: string[] = [];
  if (!name.trim()) problems.push("Укажите имя списка");
  if (refs.length === 0) problems.push("Вставьте хотя бы одну ссылку на канал/чат");
  if (!collectorId) problems.push("Выберите аккаунт-парсер (collector)");

  return (
    <div className="min-h-full">
      <ScreenHeader
        title="Поиск сообществ"
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
            value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Крипто-каналы · 10k+"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </div>

        <div className="card relative overflow-hidden p-5">
          <span className="absolute inset-y-0 left-0 w-[3px] bg-accent" aria-hidden />
          <div className="mb-3 flex items-center gap-2">
            <Link2 className="h-4 w-4 text-accent" strokeWidth={2.2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">
              Ссылки на каналы/чаты ({refs.length})
            </div>
          </div>
          <textarea
            value={refsText} onChange={(e) => setRefsText(e.target.value)}
            rows={5}
            placeholder="@ainews, https://t.me/durov, t.me/+AbCd… — по одной в строке или через запятую"
            className="w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[14px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
          <p className="mt-2 text-[12px] text-text-tertiary">
            Здесь обогащаются известные ссылки. Чтобы НАЙТИ новые каналы ниши
            (похожие + поиск + snowball) — экран «Найти каналы».
          </p>
        </div>

        <div className="card relative overflow-hidden p-5">
          <span className="absolute inset-y-0 left-0 w-[3px] bg-status-active opacity-80" aria-hidden />
          <div className="mb-2 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-status-active" strokeWidth={2.2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">Аккаунт-парсер</div>
          </div>
          <div className="flex max-h-48 flex-col gap-1.5 overflow-y-auto">
            {collectors.map((a) => (
              <button
                key={a.id} type="button" onClick={() => setCollectorId(a.id)}
                className={[
                  "flex items-center justify-between rounded-xl border p-3 text-left transition-colors",
                  collectorId === a.id ? "border-strong bg-surface-2" : "border-hairline bg-surface-1 active:bg-surface-2",
                ].join(" ")}
              >
                <div className="truncate text-[14px] font-medium text-text-primary">
                  {a.username ? `@${a.username}` : a.phone}
                </div>
                {collectorId === a.id && (
                  <span className="rounded-pill bg-status-active/15 px-2 py-0.5 text-[10px] uppercase tracking-wider text-status-active">выбран</span>
                )}
              </button>
            ))}
            {collectors.length === 0 && <p className="text-[13px] text-text-tertiary">Нет свободных аккаунтов в пуле.</p>}
          </div>
        </div>

        <div className="card p-5">
          <div className="mb-3 flex items-center gap-2">
            <Filter className="h-4 w-4 text-text-secondary" strokeWidth={2} aria-hidden />
            <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">Фильтры</div>
          </div>

          <label className="block text-[13px] font-medium text-text-secondary">Тип</label>
          <div className="mt-1 flex gap-2">
            {([["", "Любой"], ["channel", "Каналы"], ["chat", "Чаты"]] as const).map(([v, lbl]) => (
              <button
                key={v} type="button" onClick={() => setKind(v)}
                className={[
                  "flex-1 rounded-pill border px-3 py-1.5 text-[13px] font-medium",
                  kind === v ? "border-strong bg-surface-2 text-text-primary" : "border-hairline bg-surface-1 text-text-secondary",
                ].join(" ")}
              >
                {lbl}
              </button>
            ))}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="text-[13px] font-medium text-text-secondary">
              Подписчиков от
              <input type="number" min={0} value={minP}
                onChange={(e) => setMinP(e.target.value.replace(/\D/g, ""))} placeholder="любое" className={inputCls} />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">
              до
              <input type="number" min={0} value={maxP}
                onChange={(e) => setMaxP(e.target.value.replace(/\D/g, ""))} placeholder="любое" className={inputCls} />
            </label>
          </div>

          <label className="mt-3 block text-[13px] font-medium text-text-secondary">
            Последний пост ≤ дней
            <input type="number" min={0} value={lastPostMaxDays}
              onChange={(e) => setLastPostMaxDays(e.target.value.replace(/\D/g, ""))} placeholder="любой" className={inputCls} />
          </label>

          <div className="mt-3">
            <Checkbox checked={requirePublic} onChange={setRequirePublic} label="Только публичные (@username)" />
            <Checkbox checked={requireLinked} onChange={setRequireLinked} label="Только с чатом обсуждения" />
            <Checkbox checked={verifiedOnly} onChange={setVerifiedOnly} label="Только verified" />
            <Checkbox checked={excludeScamFake} onChange={setExcludeScamFake} label="Исключать scam/fake" />
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <label className="text-[13px] font-medium text-text-secondary">
              Название regex
              <input value={titleRegex} onChange={(e) => setTitleRegex(e.target.value)} placeholder="крипто|crypto"
                className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 font-mono text-[13px] text-text-primary" />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">
              @username regex
              <input value={usernameRegex} onChange={(e) => setUsernameRegex(e.target.value)} placeholder="^nft"
                className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 font-mono text-[13px] text-text-primary" />
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
              <ul className="text-[13px] text-text-secondary">{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
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
            {submit.isPending ? "Запуск…" : (<><Play className="h-4 w-4" strokeWidth={2.4} aria-hidden />Обогатить и отфильтровать</>)}
          </button>
        </div>
      </div>
    </div>
  );
}
