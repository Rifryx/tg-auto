import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, Shield, X } from "lucide-react";
import { useState } from "react";
import { timeAgo } from "../../../shared/format";
import { shillingApi } from "../api";
import type { BlacklistEntry } from "../types";

export function BlacklistTab({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [reasonFilter, setReasonFilter] = useState<"all" | "auto" | "manual">("all");

  const list = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "blacklist"],
    queryFn: () => shillingApi.blacklist(campaignId),
  });
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "blacklist"] });

  const add = useMutation({
    mutationFn: (raw: string) => {
      const trimmed = raw.trim();
      const asNum = Number(trimmed);
      const isId = Number.isFinite(asNum) && !trimmed.startsWith("@") && /^-?\d+$/.test(trimmed);
      return shillingApi.addBlacklist(campaignId, {
        chat_id: isId ? asNum : null,
        username: isId ? null : trimmed.replace(/^@/, ""),
      });
    },
    onSuccess: () => {
      setInput("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (entryId: number) => shillingApi.removeBlacklist(campaignId, entryId),
    onSuccess: invalidate,
  });

  const entries: BlacklistEntry[] = list.data ?? [];
  const filtered = entries.filter((e) => {
    if (reasonFilter === "auto" && !e.auto) return false;
    if (reasonFilter === "manual" && e.auto) return false;
    if (search) {
      const hay = `${e.username ?? ""} ${e.chat_id ?? ""} ${e.reason ?? ""}`.toLowerCase();
      if (!hay.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const exportAs = (fmt: "txt" | "csv") => {
    const rows = entries.map((e) => {
      const ident = e.username ? `@${e.username}` : String(e.chat_id ?? "");
      return fmt === "csv"
        ? `${ident},${e.auto ? "auto" : "manual"},${(e.reason ?? "").replace(/,/g, " ")}`
        : ident;
    });
    const header = fmt === "csv" ? "identifier,source,reason\n" : "";
    const blob = new Blob([header + rows.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `blacklist-${campaignId}.${fmt}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Добавление */}
      <div className="card p-4">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && input.trim() && add.mutate(input)}
            placeholder="@username или chat_id"
            className="h-11 flex-1 rounded-chip border border-hairline bg-surface-1 px-4 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
          />
          <button
            onClick={() => input.trim() && add.mutate(input)}
            disabled={!input.trim() || add.isPending}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-chip bg-accent text-accent-on active:opacity-80 disabled:opacity-40"
            aria-label="Добавить"
          >
            <Plus className="h-5 w-5" strokeWidth={2.2} aria-hidden />
          </button>
        </div>
        <p className="mt-2 text-[12px] text-text-tertiary">
          Модуль добавляет чаты автоматически при банах/отказах.
        </p>
      </div>

      {/* Фильтры + экспорт */}
      {entries.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск…"
            className="h-9 min-w-[120px] flex-1 rounded-pill border border-hairline bg-surface-1 px-3 text-[13px] text-text-primary placeholder:text-text-tertiary outline-none"
          />
          <div className="flex gap-1">
            {(["all", "auto", "manual"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setReasonFilter(r)}
                className={[
                  "rounded-pill px-3 py-1.5 text-[12px] font-medium",
                  reasonFilter === r ? "bg-surface-2 text-text-primary" : "text-text-secondary",
                ].join(" ")}
              >
                {r === "all" ? "Все" : r === "auto" ? "Авто" : "Вручную"}
              </button>
            ))}
          </div>
          <button
            onClick={() => exportAs("txt")}
            className="inline-flex h-9 items-center gap-1 rounded-pill bg-surface-2 px-3 text-[12px] text-text-secondary active:text-text-primary"
          >
            <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            TXT
          </button>
          <button
            onClick={() => exportAs("csv")}
            className="inline-flex h-9 items-center gap-1 rounded-pill bg-surface-2 px-3 text-[12px] text-text-secondary active:text-text-primary"
          >
            <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            CSV
          </button>
        </div>
      )}

      {/* Список */}
      {entries.length === 0 ? (
        <div className="flex flex-col items-center py-12 text-center">
          <Shield className="mb-3 h-10 w-10 text-text-tertiary" strokeWidth={1.5} aria-hidden />
          <p className="text-[14px] text-text-secondary">Чёрный список пуст</p>
          <p className="mt-1 max-w-[260px] text-[12px] text-text-tertiary">
            Проблемные чаты попадут сюда автоматически или добавьте вручную.
          </p>
        </div>
      ) : (
        <div className="card divide-y divide-hairline">
          {filtered.map((e) => (
            <div key={e.id} className="flex items-center gap-2 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] text-text-primary">
                  {e.username ? `@${e.username}` : `chat_id ${e.chat_id}`}
                  <span
                    className={[
                      "ml-2 rounded-pill px-2 py-0.5 text-[10px] uppercase",
                      e.auto ? "bg-surface-2 text-text-tertiary" : "bg-accent/15 text-accent",
                    ].join(" ")}
                  >
                    {e.auto ? "auto" : "вручную"}
                  </span>
                </p>
                {e.reason && <p className="truncate text-[12px] text-text-tertiary">{e.reason}</p>}
              </div>
              <span className="shrink-0 text-[11px] text-text-tertiary">{timeAgo(e.created_at)}</span>
              <button
                onClick={() => remove.mutate(e.id)}
                aria-label="Убрать из ЧС"
                className="shrink-0 text-text-tertiary active:text-status-critical"
              >
                <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
              </button>
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="px-4 py-6 text-center text-[13px] text-text-tertiary">
              Ничего не найдено.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
