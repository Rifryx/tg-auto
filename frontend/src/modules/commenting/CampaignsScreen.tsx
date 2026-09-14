import { useQuery } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
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
        <EmptyState
          icon={MessagesSquare}
          title="Пока нет кампаний"
          hint="Создайте кампанию комментирования и привяжите аккаунты из пула."
        />
      )}

      {data && (
        <div className="mt-6">
          <CapsuleButton onClick={() => navigate("/modules/commenting/campaigns/new")}>
            Создать кампанию
          </CapsuleButton>
        </div>
      )}
    </div>
  );
}
