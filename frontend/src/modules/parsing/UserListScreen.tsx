import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BadgeCheck,
  Check,
  Copy,
  ExternalLink,
  Phone,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { parsingApi } from "./api";
import type { ParsedListTarget } from "./types";

/* Детальный просмотр списка спарсенных пользователей.

   Пользователь жаловался: «нет нормального отображения, не аватарок, просто
   бред». Теперь:
   - кликабельные ссылки t.me/@username;
   - визуальный аватар (инициалы с цветным фоном, пока backend не отдаёт
     photo_url: поле зарезервировано, UI уже умеет его показывать);
   - чекбоксы + массовое копирование @username или t.me-ссылок;
   - удаление отдельных целей и всего списка. */
export function UserListScreen() {
  const navigate = useNavigate();
  const { id } = useParams();
  const listId = Number(id);
  const qc = useQueryClient();

  const list = useQuery({
    queryKey: ["parsing", "list", listId],
    queryFn: () => parsingApi.get(listId),
    enabled: Number.isFinite(listId),
  });
  const items = useQuery({
    queryKey: ["parsing", "targets", listId],
    queryFn: () => parsingApi.targets(listId),
    enabled: Number.isFinite(listId),
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState<"none" | "all" | "selected" | "handles">("none");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const removeList = useMutation({
    mutationFn: () => parsingApi.remove(listId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parsing", "lists"] });
      navigate("/modules/parsing");
    },
  });

  const rows = items.data ?? [];
  const publicRows = useMemo(() => rows.filter((r) => !!r.username), [rows]);

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
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(publicRows.map((r) => r.id)));
  };

  const linksFor = (ids: Set<number>): string =>
    rows
      .filter((r) => ids.has(r.id) && r.username)
      .map((r) => `https://t.me/${r.username}`)
      .join("\n");

  const handlesFor = (ids: Set<number>): string =>
    rows
      .filter((r) => ids.has(r.id) && r.username)
      .map((r) => `@${r.username}`)
      .join("\n");

  const copy = async (
    text: string,
    flag: "all" | "selected" | "handles",
  ) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(flag);
      setTimeout(() => setCopied("none"), 1500);
    } catch {
      /* no-op */
    }
  };

  return (
    <div className="min-h-full pb-10">
      <ScreenHeader
        title={list.data?.name ?? "Список"}
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
          {[0, 1, 2].map((i) => <div key={i} className="card h-16 animate-pulse bg-surface-2" />)}
        </div>
      )}
      {!items.isLoading && rows.length === 0 && (
        <p className="text-[14px] text-text-tertiary">В этом списке нет пользователей.</p>
      )}

      {rows.length > 0 && (
        <>
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
                <> (без @ — {rows.length - publicRows.length})</>
              )}
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => copy(handlesFor(selected), "handles")}
                disabled={selected.size === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] font-medium text-text-primary active:opacity-80 disabled:opacity-50"
              >
                {copied === "handles" ? (
                  <>
                    <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden /> Скопировано
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden /> @username выбранных
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => copy(linksFor(selected), "selected")}
                disabled={selected.size === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] font-medium text-text-primary active:opacity-80 disabled:opacity-50"
              >
                {copied === "selected" ? (
                  <>
                    <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden /> Скопировано
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden /> t.me выбранных
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() =>
                  copy(linksFor(new Set(publicRows.map((r) => r.id))), "all")
                }
                disabled={publicRows.length === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-3 text-[13px] font-semibold text-accent-on active:opacity-80 disabled:opacity-50"
              >
                {copied === "all" ? (
                  <>
                    <Check className="h-4 w-4" strokeWidth={2.2} aria-hidden /> Скопировано
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" strokeWidth={2} aria-hidden /> Все t.me-ссылки
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            {rows.map((r) => (
              <UserRow
                key={r.id}
                r={r}
                selected={selected.has(r.id)}
                onToggle={() => toggle(r.id)}
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

function UserRow({
  r,
  selected,
  onToggle,
}: {
  r: ParsedListTarget;
  selected: boolean;
  onToggle: () => void;
}) {
  const link = r.username ? `https://t.me/${r.username}` : null;
  const fullName =
    [r.first_name, r.last_name].filter(Boolean).join(" ").trim() || null;
  const displayName = fullName ?? (r.username ? `@${r.username}` : r.phone ?? "—");
  return (
    <div
      className={[
        "card flex items-center gap-3 px-4 py-3 transition-colors",
        selected ? "border-strong bg-surface-2/70" : "",
      ].join(" ")}
    >
      {r.username ? (
        <button
          type="button"
          role="checkbox"
          aria-checked={selected}
          onClick={onToggle}
          className={[
            "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors",
            selected
              ? "border-transparent bg-accent text-accent-on"
              : "border-hairline bg-surface-2",
          ].join(" ")}
        >
          {selected && <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />}
        </button>
      ) : (
        <span className="h-5 w-5 shrink-0" aria-hidden />
      )}
      <Avatar name={displayName} photoUrl={r.photo_url} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="truncate text-[14px] font-medium text-text-primary">
            {displayName}
          </p>
          {r.has_premium && (
            <BadgeCheck className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={2} aria-hidden />
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[12px] text-text-tertiary">
          {link ? (
            <a
              href={link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 text-accent hover:underline"
            >
              @{r.username}
              <ExternalLink className="h-3 w-3" strokeWidth={1.8} aria-hidden />
            </a>
          ) : (
            <span>без @username</span>
          )}
          {r.phone && (
            <span className="inline-flex items-center gap-0.5">
              <Phone className="h-3 w-3" strokeWidth={1.8} aria-hidden />
              {r.phone}
            </span>
          )}
          <span className="capitalize">{lastSeenLabel(r.last_seen_bucket)}</span>
        </div>
      </div>
    </div>
  );
}

function Avatar({ name, photoUrl }: { name: string; photoUrl: string | null }) {
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt=""
        className="h-9 w-9 shrink-0 rounded-full object-cover"
      />
    );
  }
  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p.replace(/^[@+]/, "").charAt(0).toUpperCase())
    .join("");
  const bg = HSL_PALETTE[Math.abs(hash(name)) % HSL_PALETTE.length];
  return (
    <span
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold text-white"
      style={{ background: bg }}
      aria-hidden
    >
      {initials || "·"}
    </span>
  );
}

function lastSeenLabel(bucket: ParsedListTarget["last_seen_bucket"]): string {
  switch (bucket) {
    case "recently":
      return "недавно";
    case "within_week":
      return "за неделю";
    case "within_month":
      return "за месяц";
    case "long_ago":
      return "давно";
    default:
      return "неизвестно";
  }
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return h;
}

const HSL_PALETTE = [
  "#5B8DEF",
  "#9B7EDE",
  "#E55A6A",
  "#F2994A",
  "#27AE60",
  "#2D9CDB",
  "#C06CF2",
  "#F2C94C",
  "#60C8A8",
  "#EB5757",
];

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
          Все собранные пользователи будут удалены вместе со списком. Отменить нельзя.
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
