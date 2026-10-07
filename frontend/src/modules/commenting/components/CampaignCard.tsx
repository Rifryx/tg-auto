import { useQuery } from "@tanstack/react-query";
import { ChevronRight, MessagesSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { commentingApi } from "../api";
import type { Campaign } from "../types";

export function CampaignCard({ campaign }: { campaign: Campaign }) {
  const accounts = useQuery({
    queryKey: ["campaign", campaign.id, "accounts"],
    queryFn: () => commentingApi.accounts(campaign.id),
  });
  const count = accounts.data?.length ?? 0;

  return (
    <Link
      to={`/modules/commenting/campaigns/${campaign.id}`}
      className="flex items-center gap-4 px-4 py-4 active:bg-surface-2"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <MessagesSquare className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${campaign.enabled ? "bg-status-active" : "bg-status-neutral"}`}
            aria-hidden
          />
          <span className="truncate text-[15px] font-semibold leading-tight text-text-primary">
            {campaign.name}
          </span>
        </div>
        <p className="mt-0.5 truncate text-[13px] text-text-tertiary">
          {campaign.enabled ? "Активна" : "Выключена"} · {count} акк.
        </p>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}
