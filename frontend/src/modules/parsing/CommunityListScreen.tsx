import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BadgeCheck,
  Check,
  Copy,
  ExternalLink,
  MessageSquare,
  Radio,
  Trash2,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { timeAgo } from "../../shared/format";
import { parsingApi } from "./api";
import type { CommunityItem } from "./types";

/* Детальный просмотр списка обогащённых сообществ.

   Что должно быть под рукой (запрос пользователя):
   - кликабельные ссылки t.me (а не просто «@username» текстом);
   - множественный выбор чекбоксами + массовые действия: копировать
     выбранные ссылки, копировать все;
   - удаление целого списка в заголовке. */
export function CommunityListScreen() {
  const navigate = useNavigate();
  const { id } = useParams();
  const listId = Number(id);
  const qc = useQueryClient();

  const items = useQuery({
    queryKey: ["parsing", "communities", listId],
    queryFn: () => parsingApi.communities(listId),
    enabled: Number.isFinite(listId),
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState<"none" | "all" | "selected">("none");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const removeList = useMutation({
    mutationFn: () => parsingApi.remove(listId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parsing", "lists"] });
      navigate("/modules/parsing");
    },
  });

  const rows = items.data ?? [];
  const publicRows = useMemo(
    () => rows.filter((r) => !!r.username),
    [rows],
  );

  const toggle = (rowId: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });

  const allSelected =
    publicRows.length > 0 && publicRows.every((r) => selected.has(r.id));

  const selectAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(publicRows.map((r) => r.id)));
    }
  };

  const linksFor = (ids: number[]): string => {
    const want = new Set(ids);
    return rows
      .filter((r) => want.has(r.id) && r.username)
      .map((r) => `https://t.me/${r.username}`)
      .join("\n");
  };

  const copy = async (ids: number[], flag: "all" | "selected") => {
    const text = linksFor(ids);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(flag);
      setTimeout(() => setCopied("none"), 1500);
    } catch {
      /* clipboard недоступен — беззвучно, пользователь увидит незадизейбленную кнопку */
    }
  };

  return (
    <div className="min-h-full pb-10">
      <ScreenHeader
        title="Сообщества"
        action={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              aria-label="Удалить список"
              title="Удалить список"
              className="inline-flex h-9 w-9 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-secondary hover:text-status-critical active:bg-surface-2"
            >
              <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => navigate("/modules/parsing")}
              className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              К спискам
            </button>
          </div>
        }
      />

      {items.isLoading && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="card h-20 animate-pulse bg-surface-2" />)}
        </div>
      )}
      {rows.length === 0 && !items.isLoading && (
        <p className="text-[14px] text-text-tertiary">В этом списке нет сообществ.</p>
      )}

      {rows.length > 0 && (
        <>
          {/* Панель массовых действий. Фиксируется над списком, чтобы была
              видна при скролле (sticky), но без overlay. */}
          <div className="sticky top-0 z-10 mb-3 flex flex-wrap items-center gap-2 rounded-card border border-hairline bg-bg-elevated/95 p-3 backdrop-blur">
            <button
              type="button"
              onClick={selectAll}
              disabled={publicRows.length === 0}
              className="inline-flex h-9 items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 px-3 text-[13px] font-medium text-text-primary active:bg-surface-2 disabled:opacity-50"
            >
              {allSelected ? "Снять выбор" : "Выбрать все"}
            </button>
            <span className="text-[12px] text-text-tertiary">
              Выбрано: {selected.size} / {publicRows.length}
              {publicRows.length < rows.length && (
                <> (приватные {rows.length - publicRows.length} копировать нечем)</>
              )}
            </span>
            <div className="ml-auto flex gap-2">
              <button
                type="button"
                onClick={() => copy([...selected], "selected")}
                disabled={selected.size === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] font-medium text-text-primary active:opacity-80 disabled:opacity-50"
              >
                {copied === "selected" ? (
                  <>
                    <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                    Скопировано
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden />
                    Копировать выбранные
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => copy(publicRows.map((r) => r.id), "all")}
                disabled={publicRows.length === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-3 text-[13px] font-semibold text-accent-on active:opacity-80 disabled:opacity-50"
              >
                {copied === "all" ? (
                  <>
                    <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                    Скопировано
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden />
                    Копировать все ссылки
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            {rows.map((c) => (
              <CommunityRow
                key={c.id}
                c={c}
                selected={selected.has(c.id)}
                onToggle={() => toggle(c.id)}
              />
            ))}
          </div>
        </>
      )}

      {confirmDelete && (
        <ConfirmDeleteList
          busy={removeList.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => removeList.mutate()}
        />
      )}
    </div>
  );
}

function CommunityRow({
  c,
  selected,
  onToggle,
}: {
  c: CommunityItem;
  selected: boolean;
  onToggle: () => void;
}) {
  const Icon = c.kind === "chat" ? MessageSquare : Radio;
  const link = c.username ? `https://t.me/${c.username}` : null;
  return (
    <div
      className={[
        "card flex items-start gap-3 p-4 transition-colors",
        selected ? "border-strong bg-surface-2/70" : "",
      ].join(" ")}
    >
      {/* Чекбокс — только для публичных (приватные не скопируешь). */}
      {c.username ? (
        <button
          type="button"
          role="checkbox"
          aria-checked={selected}
          onClick={onToggle}
          className={[
            "mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors",
            selected
              ? "border-transparent bg-accent text-accent-on"
              : "border-hairline bg-surface-2",
          ].join(" ")}
        >
          {selected && <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />}
        </button>
      ) : (
        <span className="mt-1 h-5 w-5 shrink-0" aria-hidden />
      )}

      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Icon className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <h3 className="truncate text-[15px] font-semibold text-text-primary">
            {c.title ?? c.input_ref}
          </h3>
          {c.is_verified && (
            <BadgeCheck className="h-4 w-4 shrink-0 text-accent" strokeWidth={2} aria-hidden />
          )}
          {(c.is_scam || c.is_fake) && (
            <span className="rounded-pill bg-status-critical/15 px-1.5 text-[10px] font-semibold uppercase text-status-critical">
              {c.is_scam ? "scam" : "fake"}
            </span>
          )}
        </div>
        {/* Кликабельная ссылка t.me, если канал публичный. */}
        {link ? (
          <a
            href={link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline"
          >
            @{c.username}
            <ExternalLink className="h-3 w-3" strokeWidth={1.8} aria-hidden />
          </a>
        ) : (
          <p className="text-[13px] text-text-tertiary">приватный</p>
        )}
        <p className="truncate text-[12px] text-text-tertiary">
          {c.kind === "chat" ? "чат" : "канал"}
          {c.has_linked_chat ? " · с обсуждением" : ""}
          {c.last_post_at ? ` · посл. пост ${timeAgo(c.last_post_at)}` : " · постов не видно"}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div className="flex items-center gap-1 text-[16px] font-bold tabular-nums text-text-primary">
          <Users className="h-3.5 w-3.5 text-text-tertiary" strokeWidth={2} aria-hidden />
          {c.participants_count != null ? fmt(c.participants_count) : "—"}
        </div>
      </div>
    </div>
  );
}

function ConfirmDeleteList({
  busy,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center lg:p-6">
      <div onClick={onCancel} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        className="relative mx-auto w-full max-w-[440px] rounded-t-[28px] border border-hairline bg-bg-elevated p-5 pb-[calc(env(safe-area-inset-bottom)+16px)] lg:rounded-[28px] lg:pb-5"
      >
        <h2 className="text-[18px] font-bold text-text-primary">Удалить этот список?</h2>
        <p className="mt-1 text-[13px] text-text-tertiary">
          Все собранные в нём сообщества будут удалены вместе со списком. Отменить нельзя.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-pill border border-hairline bg-surface-2 px-4 py-3 text-[14px] font-medium text-text-primary active:opacity-80 disabled:opacity-60"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex-1 rounded-pill bg-status-critical/90 px-4 py-3 text-[14px] font-semibold text-white active:opacity-80 disabled:opacity-60"
          >
            {busy ? "Удаляем…" : "Удалить"}
          </button>
        </div>
      </div>
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
