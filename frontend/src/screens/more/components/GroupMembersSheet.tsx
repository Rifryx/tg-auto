import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AccountPickRow } from "../../../modules/commenting/components/AccountPickRow";
import { CapsuleButton } from "../../../modules/commenting/components/ui";
import { accountsApi } from "../../../shared/accounts";
import { projectsApi } from "../../../shared/projects";
import type { Project } from "../../../shared/types";

/* Состав группы аккаунтов: отметить галочками, сохранить одним запросом.
   У аккаунта одна группа — если он в другой, показываем это, и при
   сохранении он переедет сюда.
   Телефон: шторка снизу. Десктоп: окно по центру. */
export function GroupMembersSheet({
  group,
  groups,
  onClose,
}: {
  group: Project;
  groups: Project[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const [selected, setSelected] = useState<Set<number> | null>(null);
  const [query, setQuery] = useState("");

  // Стартовое выделение — текущие участники группы (когда список загрузился).
  useEffect(() => {
    if (accounts.data && selected === null) {
      setSelected(new Set(accounts.data.filter((a) => a.project_id === group.id).map((a) => a.id)));
    }
  }, [accounts.data, group.id, selected]);

  const groupName = useMemo(() => new Map(groups.map((g) => [g.id, g.name])), [groups]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/[\s+()-]/g, "");
    const list = accounts.data ?? [];
    if (!q) return list;
    return list.filter((a) =>
      [a.phone, a.username ?? "", a.first_name ?? "", String(a.id)].some((v) =>
        v.toLowerCase().replace(/[\s+()-]/g, "").includes(q),
      ),
    );
  }, [accounts.data, query]);

  const save = useMutation({
    mutationFn: () => projectsApi.setAccounts(group.id, [...(selected ?? [])]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      onClose();
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const sel = selected ?? new Set<number>();
  const allVisibleSelected = visible.length > 0 && visible.every((a) => sel.has(a.id));
  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s ?? []);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const toggleAllVisible = () =>
    setSelected((s) => {
      const n = new Set(s ?? []);
      visible.forEach((a) => (allVisibleSelected ? n.delete(a.id) : n.add(a.id)));
      return n;
    });

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)] lg:items-center lg:justify-center lg:p-8"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Аккаунты группы ${group.name}`}
        className="mx-auto flex max-h-[85vh] w-full max-w-[440px] flex-col rounded-t-card border-t border-strong bg-bg-elevated lg:max-w-[560px] lg:rounded-card lg:border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 pb-3 pt-5">
          <div className="min-w-0">
            <h3 className="truncate text-[17px] font-semibold text-text-primary">{group.name}</h3>
            <p className="text-[12px] text-text-tertiary">
              Отметьте аккаунты группы · выбрано {sel.size}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-secondary hover:text-text-primary"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="flex items-center gap-2 px-5 pb-3">
          <label className="flex min-h-[44px] flex-1 items-center gap-2 rounded-chip border border-hairline bg-surface-1 px-3 focus-within:border-strong">
            <Search className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Телефон, username, ID"
              className="w-full bg-transparent text-[15px] text-text-primary placeholder:text-text-tertiary outline-none"
            />
          </label>
          <button
            type="button"
            onClick={toggleAllVisible}
            disabled={visible.length === 0}
            className="min-h-[44px] shrink-0 rounded-chip border border-hairline bg-surface-1 px-3 text-[13px] text-text-secondary hover:text-text-primary disabled:opacity-40"
          >
            {allVisibleSelected ? "Снять все" : "Выбрать все"}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 [scrollbar-width:thin]">
          {accounts.isLoading ? (
            <p className="py-8 text-center text-[13px] text-text-tertiary">Загрузка…</p>
          ) : visible.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-text-tertiary">
              {query ? "Ничего не найдено." : "Аккаунтов пока нет."}
            </p>
          ) : (
            <div className="flex flex-col gap-2 pb-2">
              {visible.map((a) => {
                const other =
                  a.project_id != null && a.project_id !== group.id
                    ? groupName.get(a.project_id)
                    : undefined;
                return (
                  <AccountPickRow
                    key={a.id}
                    account={a}
                    selected={sel.has(a.id)}
                    onToggle={() => toggle(a.id)}
                    note={other ? `сейчас в «${other}»` : undefined}
                  />
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-hairline px-5 pb-[calc(env(safe-area-inset-bottom)+14px)] pt-3 lg:pb-4">
          {save.isError && (
            <p className="mb-2 text-[12px] text-status-critical">
              {save.error instanceof Error ? save.error.message : "Не удалось сохранить"}
            </p>
          )}
          <CapsuleButton disabled={selected === null || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Сохраняем…" : `Сохранить состав (${sel.size})`}
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
