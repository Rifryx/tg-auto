import { useQuery } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { LimitBanner } from "../../shared/LimitBanner";
import { useLimit } from "../../shared/limits";
import { commentingApi } from "./api";
import { CampaignCard } from "./components/CampaignCard";
import { CapsuleButton } from "./components/ui";

export function CampaignsScreen() {
  const navigate = useNavigate();
  const limit = useLimit("campaigns_active_max");
  const blocked = limit?.atLimit ?? false;
  const { data, isLoading, isError } = useQuery({
    queryKey: ["campaigns"],
    queryFn: commentingApi.list,
  });

  return (
    <div className="min-h-full">
      <ScreenHeader title="Кампании" />

      <LimitBanner feature="campaigns_active_max" />

      {isLoading && (
        <div className="card overflow-hidden">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className={`h-[72px] animate-pulse bg-surface-2 ${i > 0 ? "border-t border-hairline" : ""}`} />
          ))}
        </div>
      )}

      {isError && <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить.</p>}

      {data && data.length > 0 && (
        <div className="card overflow-hidden p-0">
          {data.map((c, i) => (
            <div key={c.id} className={i > 0 ? "border-t border-hairline" : ""}>
              <CampaignCard campaign={c} />
            </div>
          ))}
        </div>
      )}

      {data && data.length === 0 && (
        <EmptyState
          icon={MessagesSquare}
          title="Пока нет кампаний"
          hint="Создайте кампанию комментирования и привяжите аккаунты из пула."
        />
      )}

      {data && (
        <div className="mt-6">
          <CapsuleButton
            variant={blocked ? "secondary" : "accent"}
            disabled={blocked}
            onClick={() => {
              if (blocked) return navigate("/billing");
              navigate("/modules/commenting/campaigns/new");
            }}
          >
            {blocked ? "Лимит достигнут" : "Создать кампанию"}
          </CapsuleButton>
        </div>
      )}
    </div>
  );
}
