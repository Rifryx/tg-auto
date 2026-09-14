import { useQuery } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { accountsApi } from "../../shared/accounts";
import { AccountRow } from "./components/AccountRow";
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

  const { data, isLoading, isError } = useQuery({
    queryKey: ["accounts", filter],
    queryFn: () => accountsApi.list(filter),
  });

  return (
    <>
      <ScreenHeader
        title="Аккаунты"
        action={
          <button
            onClick={() => navigate("/accounts/new")}
            aria-label="Добавить аккаунт"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-on active:opacity-70"
          >
            <Plus className="h-5 w-5" strokeWidth={2} aria-hidden />
          </button>
        }
      />

      <FilterPills value={filter} onChange={setFilter} />

      {isLoading && <ListSkeleton />}

      {isError && (
        <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить список.</p>
      )}

      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((a) => (
            <AccountRow key={a.id} account={a} />
          ))}
        </div>
      )}

      {data && data.length === 0 && (
        <EmptyState
          icon={Users}
          title="Пока нет аккаунтов"
          hint={
            filter === "all"
              ? "Подключите Telegram-аккаунт, чтобы начать прогрев."
              : "В этом фильтре аккаунтов нет."
          }
        />
      )}

      {data && data.length === 0 && filter === "all" && (
        <div className="mt-6">
          <CapsuleButton onClick={() => navigate("/accounts/new")}>
            Добавить аккаунт
          </CapsuleButton>
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
