import { useQuery } from "@tanstack/react-query";
import { Lock, Plus, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { accountsApi } from "../../shared/accounts";
import { LimitBanner } from "../../shared/LimitBanner";
import { useLimit } from "../../shared/limits";
import { hapticSelection } from "../../shared/tg";
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
        }
      />

      <LimitBanner feature="accounts_max" />

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
