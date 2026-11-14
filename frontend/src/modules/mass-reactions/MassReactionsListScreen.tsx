import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Plus, SmilePlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { massReactionsApi } from "./api";
import { STATUS_LABEL, STATUS_TONE } from "./labels";
import type { MassReactionCampaign } from "./types";

export function MassReactionsListScreen() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["mass-reactions", "campaigns"],
    queryFn: massReactionsApi.list,
    refetchInterval: 30_000,
  });

  return (
    <>
      <ScreenHeader
        title="Масс-реакции"
        action={
          <button
            onClick={() => navigate("/modules/mass-reactions/campaigns/new")}
            aria-label="Новая кампания"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-on active:opacity-70"
          >
            <Plus className="h-5 w-5" strokeWidth={2} aria-hidden />
          </button>
        }
      />

      {isLoading && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-[76px] animate-pulse bg-surface-2" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить список.</p>
      )}

      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((c) => (
            <CampaignRow key={c.id} campaign={c} />
          ))}
        </div>
      )}

      {data && data.length === 0 && (
        <EmptyState
          icon={SmilePlus}
          title="Пока нет кампаний"
          hint="Боты ставят реакции на сообщения людей в чатах — автор видит уведомление и заходит в профиль."
        />
      )}
    </>
  );
}

function CampaignRow({ campaign }: { campaign: MassReactionCampaign }) {
  return (
    <Link
      to={`/modules/mass-reactions/campaigns/${campaign.id}`}
      className="card flex items-center gap-3 px-4 py-4 transition-colors active:bg-surface-2"
    >
      <span
        className={`h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_TONE[campaign.status]}`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-text-primary">{campaign.name}</p>
        <p className="mt-0.5 truncate text-[12px] text-text-tertiary">
          {STATUS_LABEL[campaign.status]} · каждое {campaign.every_n_message}-е ·{" "}
          {campaign.probability_percent}% · {campaign.reaction_emojis.slice(0, 6).join(" ")}
        </p>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}
