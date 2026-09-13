import { useQuery } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { commentingApi } from "../api";
import type { Campaign } from "../types";

/* Карточка-«папка» кампании (§9, паттерн All Drafts): иконка, название,
   target_channel, счётчик привязанных аккаунтов внизу справа, status-dot
   enabled/disabled в углу. */
export function CampaignCard({ campaign }: { campaign: Campaign }) {
  const accounts = useQuery({
    queryKey: ["campaign", campaign.id, "accounts"],
    queryFn: () => commentingApi.accounts(campaign.id),
  });
  const count = accounts.data?.length ?? 0;

  return (
    <Link
      to={`/modules/commenting/campaigns/${campaign.id}`}
      className="card relative flex aspect-square flex-col justify-between p-4 active:bg-surface-2"
    >
      <span
        className={`absolute right-4 top-4 h-2 w-2 rounded-full ${campaign.enabled ? "bg-status-active" : "bg-status-neutral"}`}
        aria-label={campaign.enabled ? "включена" : "выключена"}
      />
      <MessagesSquare className="h-7 w-7 text-text-secondary" strokeWidth={1.6} aria-hidden />
      <div>
        <p className="truncate text-[15px] font-semibold text-text-primary">{campaign.name}</p>
        <p className="truncate text-[13px] text-text-secondary">{campaign.target_channel}</p>
        <p className="mt-2 text-right text-[13px] text-text-tertiary nums">
          {count} акк.
        </p>
      </div>
    </Link>
  );
}
