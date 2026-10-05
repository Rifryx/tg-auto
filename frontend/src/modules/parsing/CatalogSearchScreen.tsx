import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, Check, Database, Search, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { accountsApi } from "../../shared/accounts";
import { ApiError } from "../../shared/api";
import { parsingApi } from "./api";
import type { CatalogCandidate } from "./types";

/* Поиск сообществ во внешнем каталоге (Telemetr.io) — Discovery, этап 3.
   Найденное сохраняется через нативную верификацию (run/communities). */

const inputCls =
  "mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] text-text-primary";

export function CatalogSearchScreen() {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("");
  const [country, setCountry] = useState("");
  const [minP, setMinP] = useState("");
  const [maxP, setMaxP] = useState("");
  const [kind, setKind] = useState<"" | "channel" | "chat">("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [listName, setListName] = useState("");
  const [collectorId, setCollectorId] = useState<number | null>(null);

  const status = useQuery({
    queryKey: ["parsing", "catalog", "status"],
    queryFn: () => parsingApi.catalogStatus(),
    retry: false,
  });
  const keyMissing =
    status.isError && status.error instanceof ApiError && status.error.status === 503;

  const accountsQuery = useQuery({ queryKey: ["accounts", "pool"], queryFn: () => accountsApi.list() });
  const collectors = useMemo(
    () => (accountsQuery.data ?? []).filter((a) => a.status === "pool"),
    [accountsQuery.data],
  );

  const search = useMutation({
    mutationFn: () =>
      parsingApi.catalogSearch({
        term: term.trim() || null,
        category: category.trim() || null,
        language: language.trim() || null,
        country: country.trim() || null,
        min_participants: minP ? Number(minP) : null,
        max_participants: maxP ? Number(maxP) : null,
        kind: kind || null,
        limit: 50,
      }),
    onSuccess: () => setSelected(new Set()),
  });

  const save = useMutation({
    mutationFn: () => {
      const refs = [...selected];
      return parsingApi.runCommunities({
        name: listName.trim(),
        collector_account_id: collectorId!,
        refs,
        exclude_scam_fake: true,
      });
    },
    onSuccess: () => navigate("/modules/parsing"),
  });

  const results = search.data ?? [];
  const selectable = results.filter((r) => r.username);
  const toggle = (ref: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });

  const canSearch = (term.trim() || category.trim() || language.trim() || country.trim() || minP || maxP) && !search.isPending;
  const canSave = selected.size > 0 && listName.trim() && collectorId != null && !save.isPending;

  return (
    <div className="min-h-full">
      <ScreenHeader
        title="Каталог сообществ"
        action={
          <button type="button" onClick={() => navigate("/modules/parsing")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary">
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К спискам
          </button>
        }
      />

      {keyMissing && (
        <div className="mb-4 rounded-xl border-l-[4px] border-status-warning bg-surface-1 p-4">
          <p className="text-[14px] font-medium text-text-primary">Каталог не подключён</p>
          <p className="mt-1 text-[13px] text-text-secondary">
            Укажите ключ Telemetr.io в <span className="font-mono">TELEMETRIO_API_KEY</span>.
            Получить: <b>@telemetrio_api_bot</b> → команда <span className="font-mono">/api_key</span>.
          </p>
        </div>
      )}
      {status.data?.ok && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-surface-1 px-4 py-2 text-[13px] text-status-active">
          <Database className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          Каталог подключён ({status.data.provider})
        </div>
      )}

      <div className="flex flex-col gap-4">
        <div className="card relative overflow-hidden p-5">
          <span className="absolute inset-y-0 left-0 w-[3px] bg-accent" aria-hidden />
          <div className="mb-3 text-[13px] font-medium uppercase tracking-wider text-text-secondary">Критерии поиска</div>
          <label className="block text-[13px] font-medium text-text-secondary">Ключевое слово / тема
            <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="crypto, нейросети…" className={inputCls} />
          </label>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <label className="text-[13px] font-medium text-text-secondary">Категория
              <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="tech" className={inputCls} />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">Язык
              <input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="ru" className={inputCls} />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">Страна
              <input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="RU" className={inputCls} />
            </label>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="text-[13px] font-medium text-text-secondary">Подписчиков от
              <input type="number" min={0} value={minP} onChange={(e) => setMinP(e.target.value.replace(/\D/g, ""))} placeholder="любое" className={inputCls} />
            </label>
            <label className="text-[13px] font-medium text-text-secondary">до
              <input type="number" min={0} value={maxP} onChange={(e) => setMaxP(e.target.value.replace(/\D/g, ""))} placeholder="любое" className={inputCls} />
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            {([["", "Любой"], ["channel", "Каналы"], ["chat", "Чаты"]] as const).map(([v, lbl]) => (
              <button key={v} type="button" onClick={() => setKind(v)}
                className={["flex-1 rounded-pill border px-3 py-1.5 text-[13px] font-medium",
                  kind === v ? "border-strong bg-surface-2 text-text-primary" : "border-hairline bg-surface-1 text-text-secondary"].join(" ")}>
                {lbl}
              </button>
            ))}
          </div>
          <button type="button" disabled={!canSearch}
            onClick={() => search.mutate()}
            className={["mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-pill text-[15px] font-semibold",
              canSearch ? "bg-accent text-accent-on active:opacity-80" : "bg-surface-2 text-text-tertiary"].join(" ")}>
            <Search className="h-4 w-4" strokeWidth={2.2} aria-hidden />
            {search.isPending ? "Ищем…" : "Найти в каталоге"}
          </button>
          {search.isError && (
            <p className="mt-2 text-[13px] text-status-critical">
              {search.error instanceof ApiError && search.error.status === 503
                ? "Каталог недоступен — проверьте ключ."
                : "Не удалось выполнить поиск."}
            </p>
          )}
        </div>

        {results.length > 0 && (
          <div className="card p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-[13px] font-medium uppercase tracking-wider text-text-secondary">
                Найдено: {results.length} · выбрано {selected.size}
              </div>
              <button type="button" onClick={() => setSelected(new Set(selectable.map((r) => r.ref)))}
                className="text-[13px] font-medium text-accent active:opacity-70">
                Выбрать все
              </button>
            </div>
            <div className="flex flex-col gap-1.5">
              {results.map((c) => <CandidateRow key={c.ref} c={c} on={selected.has(c.ref)} onToggle={() => c.username && toggle(c.ref)} />)}
            </div>
            <p className="mt-2 text-[12px] text-text-tertiary">
              Выбрать можно только публичные (@username) — их проверит collector-аккаунт.
            </p>
          </div>
        )}

        {selected.size > 0 && (
          <div className="card p-5">
            <div className="mb-3 text-[13px] font-medium uppercase tracking-wider text-text-secondary">
              Сохранить и проверить ({selected.size})
            </div>
            <label className="block text-[13px] font-medium text-text-secondary">Имя списка
              <input value={listName} onChange={(e) => setListName(e.target.value)} placeholder="Крипто-каналы · каталог" className={inputCls} />
            </label>
            <div className="mt-3 flex max-h-40 flex-col gap-1.5 overflow-y-auto">
              {collectors.map((a) => (
                <button key={a.id} type="button" onClick={() => setCollectorId(a.id)}
                  className={["flex items-center justify-between rounded-xl border p-2.5 text-left",
                    collectorId === a.id ? "border-strong bg-surface-2" : "border-hairline bg-surface-1"].join(" ")}>
                  <span className="truncate text-[14px] text-text-primary">{a.username ? `@${a.username}` : a.phone}</span>
                  {collectorId === a.id && <span className="text-[11px] uppercase text-status-active">collector</span>}
                </button>
              ))}
              {collectors.length === 0 && <p className="text-[13px] text-text-tertiary">Нет свободных аккаунтов в пуле.</p>}
            </div>
            <button type="button" disabled={!canSave} onClick={() => save.mutate()}
              className={["mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-pill text-[15px] font-semibold",
                canSave ? "bg-accent text-accent-on active:opacity-80" : "bg-surface-2 text-text-tertiary"].join(" ")}>
              {save.isPending ? "Сохраняем…" : "Сохранить и проверить нативно"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CandidateRow({ c, on, onToggle }: { c: CatalogCandidate; on: boolean; onToggle: () => void }) {
  const disabled = !c.username;
  return (
    <button type="button" onClick={onToggle} disabled={disabled}
      className={["flex items-center gap-3 rounded-xl border p-3 text-left transition-colors",
        disabled ? "border-hairline bg-surface-1 opacity-50" : on ? "border-strong bg-surface-2" : "border-hairline bg-surface-1"].join(" ")}>
      <span className={["flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] border",
        on ? "border-accent bg-accent text-accent-on" : "border-strong bg-surface-1"].join(" ")}>
        {on && <Check className="h-3.5 w-3.5" strokeWidth={2.5} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[14px] font-medium text-text-primary">{c.title ?? c.ref}</span>
          {c.verified && <BadgeCheck className="h-4 w-4 shrink-0 text-accent" strokeWidth={2} aria-hidden />}
        </div>
        <div className="truncate text-[12px] text-text-tertiary">
          {c.username ? `@${c.username}` : "приватный"} · {c.kind === "chat" ? "чат" : "канал"}
          {c.category ? ` · ${c.category}` : ""}{c.language ? ` · ${c.language}` : ""}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 text-[14px] font-bold tabular-nums text-text-primary">
        <Users className="h-3.5 w-3.5 text-text-tertiary" strokeWidth={2} aria-hidden />
        {c.participants_count != null ? fmt(c.participants_count) : "—"}
      </div>
    </button>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
