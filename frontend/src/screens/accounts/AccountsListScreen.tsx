import { useQuery } from "@tanstack/react-query";
import { CheckSquare, Lock, Plus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { projectsApi } from "../../shared/projects";
import { Select } from "../../shared/Select";
import { LimitBanner } from "../../shared/LimitBanner";
import { useLimit } from "../../shared/limits";
import { ROLE_LABEL } from "../../shared/status";
import { hapticSelection } from "../../shared/tg";
import { AccountRow } from "./components/AccountRow";
import { BulkActionBar } from "./components/BulkActionBar";
import { FilterPills, type AccountFilter } from "./components/FilterPills";
import { CapsuleButton } from "./components/ui";

const FILTER_VALUES = ["all", "pool", "assigned", "warming", "cooldown", "banned"];

export function AccountsListScreen() {
  const navigate = useNavigate();
  // Начальный фильтр из ?status=X (переход с KPI-карточки дашборда).
  const [params] = useSearchParams();
  const initial = params.get("status");
  const [filter, setFilter] = useState<AccountFilter>(
    initial && FILTER_VALUES.includes(initial) ? (initial as AccountFilter) : "all",
  );

  // Группа: "" — все, "none" — без группы, иначе id. Можно прийти по ?group=<id>.
  const [group, setGroup] = useState<string>(params.get("group") ?? "");
  // Роль: "" — все, "none" — без роли, иначе значение AccountRole.
  const [role, setRole] = useState<string>(params.get("role") ?? "");

  const { data: byStatus, isLoading, isError } = useQuery({
    queryKey: ["accounts", filter],
    queryFn: () => accountsApi.list(filter),
  });
  const groups = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });
  const groupName = useMemo(
    () => new Map((groups.data ?? []).map((g) => [g.id, g.name])),
    [groups.data],
  );
  const proxies = useQuery({ queryKey: ["proxies"], queryFn: catalogApi.proxies });
  const proxyById = useMemo(
    () => new Map((proxies.data ?? []).map((p) => [p.id, p])),
    [proxies.data],
  );

  // Режим массового выбора + набор выбранных id (этап 2).
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toggleSelect = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const exitSelect = () => {
    setSelected(new Set());
    setSelectMode(false);
  };
  const data = useMemo(() => {
    if (!byStatus) return byStatus;
    let rows = byStatus;
    if (group === "none") rows = rows.filter((a) => a.project_id == null);
    else if (group !== "") rows = rows.filter((a) => a.project_id === Number(group));
    if (role === "none") rows = rows.filter((a) => a.role == null);
    else if (role !== "") rows = rows.filter((a) => a.role === role);
    return rows;
  }, [byStatus, group, role]);

  const limit = useLimit("accounts_max");
  const blocked = limit?.atLimit ?? false;
  const goNew = () => {
    hapticSelection();
    if (blocked) navigate("/billing");
    else navigate("/accounts/new");
  };

  return (
    <>
      <ScreenHeader
        title="Аккаунты"
        action={
          <div className="flex items-center gap-2">
            {selectMode ? (
              <button
                onClick={exitSelect}
                className="flex h-10 items-center rounded-full border border-hairline bg-surface-1 px-4 text-[14px] font-medium text-text-secondary active:text-text-primary"
              >
                Готово
              </button>
            ) : (
              <button
                onClick={() => {
                  hapticSelection();
                  setSelectMode(true);
                }}
                aria-label="Выбрать аккаунты"
                className="flex h-10 w-10 items-center justify-center rounded-full border border-hairline bg-surface-1 text-text-secondary active:text-text-primary"
              >
                <CheckSquare className="h-5 w-5" strokeWidth={1.8} aria-hidden />
              </button>
            )}
            <button
              onClick={goNew}
              aria-label={blocked ? "Лимит достигнут — перейти к тарифу" : "Добавить аккаунт"}
              className={
                blocked
                  ? "flex h-10 w-10 items-center justify-center rounded-full border border-hairline bg-surface-1 text-text-secondary"
                  : "flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-on active:opacity-70"
              }
            >
              {blocked ? (
                <Lock className="h-4 w-4" strokeWidth={2} aria-hidden />
              ) : (
                <Plus className="h-5 w-5" strokeWidth={2} aria-hidden />
              )}
            </button>
          </div>
        }
      />

      <LimitBanner feature="accounts_max" />

      <div className="lg:flex lg:items-start lg:justify-between lg:gap-4">
        <FilterPills value={filter} onChange={setFilter} />
        <div className="lg:flex lg:shrink-0 lg:gap-3">
          {(groups.data?.length ?? 0) > 0 && (
            <Select
              className="mb-4 lg:w-[220px]"
              value={group}
              onChange={setGroup}
              options={[
                { value: "", label: "Все группы" },
                { value: "none", label: "Без группы" },
                ...(groups.data ?? []).map((g) => ({ value: String(g.id), label: g.name })),
              ]}
            />
          )}
          <Select
            className="mb-4 lg:w-[200px]"
            value={role}
            onChange={setRole}
            options={[
              { value: "", label: "Все роли" },
              { value: "none", label: "Без роли" },
              ...Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label })),
            ]}
          />
        </div>
      </div>

      {isLoading && <ListSkeleton />}

      {isError && (
        <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить список.</p>
      )}

      {selectMode && data && data.length > 0 && (
        <div className="mb-2 flex items-center justify-between px-1">
          <button
            onClick={() => setSelected(new Set(data.map((a) => a.id)))}
            className="text-[13px] font-medium text-accent active:opacity-70"
          >
            Выбрать все ({data.length})
          </button>
          {selected.size > 0 && (
            <button
              onClick={() => setSelected(new Set())}
              className="text-[13px] text-text-secondary active:text-text-primary"
            >
              Сбросить
            </button>
          )}
        </div>
      )}

      {data && data.length > 0 && (
        <div className={`grid gap-2 lg:grid-cols-2 xl:grid-cols-3 ${selectMode ? "pb-28" : ""}`}>
          {data.map((a) => (
            <AccountRow
              key={a.id}
              account={a}
              groupName={a.project_id != null ? groupName.get(a.project_id) : undefined}
              proxy={a.proxy_id != null ? proxyById.get(a.proxy_id) : undefined}
              selectable={selectMode}
              selected={selected.has(a.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {selectMode && (
        <BulkActionBar selectedIds={[...selected]} onClear={exitSelect} />
      )}

      {data && data.length === 0 && (
        <EmptyState
          icon={Users}
          title="Пока нет аккаунтов"
          hint={
            filter === "all" && group === ""
              ? "Подключите Telegram-аккаунт, чтобы начать прогрев."
              : "В этом фильтре аккаунтов нет."
          }
        />
      )}

      {data && data.length === 0 && filter === "all" && group === "" && (
        <div className="mt-6 flex flex-col gap-2">
          <CapsuleButton
            variant={blocked ? "secondary" : "accent"}
            disabled={blocked}
            onClick={goNew}
          >
            {blocked ? "Лимит достигнут" : "Добавить аккаунт"}
          </CapsuleButton>
          <CapsuleButton
            variant="secondary"
            onClick={() => navigate("/accounts/import-bulk")}
          >
            Массовый импорт
          </CapsuleButton>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => navigate("/accounts/import-bulk")}
            className="text-[13px] text-text-tertiary underline-offset-2 hover:underline"
          >
            Массовый импорт из архива
          </button>
        </div>
      )}
    </>
  );
}

/* Skeleton без спиннера — пульсация в оттенках surface (§ треб.). */
function ListSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="card h-16 animate-pulse bg-surface-2" />
      ))}
    </div>
  );
}
