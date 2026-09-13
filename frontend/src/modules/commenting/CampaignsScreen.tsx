import { useQuery } from "@tanstack/react-query";
import { MessagesSquare, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { commentingApi } from "./api";
import { CampaignCard } from "./components/CampaignCard";
import { CapsuleButton } from "./components/ui";

export function CampaignsScreen() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["campaigns"],
    queryFn: commentingApi.list,
  });

  return (
    <div className="min-h-full">
      <ScreenHeader title="Кампании" />

      {isLoading && (
        <div className="grid grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card aspect-square animate-pulse bg-surface-2" />
          ))}
        </div>
      )}

      {isError && <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить.</p>}

      {data && data.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {data.map((c) => (
            <CampaignCard key={c.id} campaign={c} />
          ))}
        </div>
      )}

      {data && data.length === 0 && (
        <>
          <EmptyState
            icon={MessagesSquare}
            title="Пока нет кампаний"
            hint="Создайте кампанию комментирования и привяжите аккаунты из пула."
          />
          <div className="mt-6">
            <CapsuleButton onClick={() => navigate("/modules/commenting/campaigns/new")}>
              Создать кампанию
            </CapsuleButton>
          </div>
        </>
      )}

      {/* FAB — плавает над капсульным навбаром, снизу справа. */}
      <button
        onClick={() => navigate("/modules/commenting/campaigns/new")}
        aria-label="Создать кампанию"
        className="fixed right-5 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-on shadow-none active:opacity-70"
        style={{ bottom: "calc(env(safe-area-inset-bottom) + 92px)" }}
      >
        <Plus className="h-6 w-6" strokeWidth={2.2} aria-hidden />
      </button>
    </div>
  );
}
