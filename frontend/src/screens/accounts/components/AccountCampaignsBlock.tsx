import { useQuery } from "@tanstack/react-query";
import { Briefcase } from "lucide-react";
import { Link } from "react-router-dom";
import { commentingApi } from "../../../modules/commenting/api";
import type { Campaign } from "../../../modules/commenting/types";
import { CONTAINER_LABEL } from "../../../shared/status";

/** Все commenting-кампании аккаунта (multi-campaign, миграция 0067).
 *  Пользователь жаловался «нет якоря и ссылки на кампанию в которой он
 *  якобы работает». Теперь показываем КАЖДУЮ привязку с ссылкой; если
 *  assigned_container_id указывает на кампанию, которой нет в БД — явная
 *  «застрял в удалённой кампании» плашка. */
export function AccountCampaignsBlock({
  accountId,
  assignedType,
  assignedId,
  commentingCampaigns,
}: {
  accountId: number;
  assignedType: string | null;
  assignedId: number | null;
  commentingCampaigns: Campaign[];
}) {
  const links = useQuery({
    queryKey: ["account", accountId, "commenting-campaigns"],
    queryFn: () => commentingApi.campaignsOfAccount(accountId),
    refetchInterval: 20_000,
  });
  const campaignById = new Map(commentingCampaigns.map((c) => [c.id, c]));

  // Легаси-инцидент: аккаунт помечен как assigned с container_id, но ни одной
  // привязки нет (кампания удалена без корректного detach из PR #67).
  const stale =
    links.data != null &&
    links.data.length === 0 &&
    assignedType === "commenting" &&
    assignedId != null;

  if (stale) {
    return (
      <div className="mb-3 flex flex-col gap-1 rounded-chip border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-[13px] text-status-warning">
        <p className="font-medium">
          Застрял в удалённой кампании #{assignedId}
        </p>
        <p className="text-[12px] opacity-80">
          Кампания больше не существует, но аккаунт всё ещё помечен как «в
          работе». Нажмите «Освободить (вернуть в пул)» ниже.
        </p>
      </div>
    );
  }

  // Non-commenting контейнер (shilling/priming) — показываем как есть.
  if (assignedType && assignedType !== "commenting") {
    const typeLabel = CONTAINER_LABEL[assignedType] ?? assignedType;
    const href =
      assignedType === "shilling"
        ? "/modules/shilling/campaigns"
        : assignedType === "priming"
          ? "/modules/priming/campaigns"
          : null;
    return (
      <div className="mb-3 flex items-start gap-2 rounded-chip border border-hairline bg-surface-1 px-3 py-2 text-[13px] text-text-secondary">
        <Briefcase className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[12px] text-text-tertiary">В работе в {typeLabel}</p>
          {href && assignedId != null ? (
            <Link
              to={`${href}/${assignedId}`}
              className="truncate font-medium text-accent hover:underline"
            >
              Открыть кампанию #{assignedId}
            </Link>
          ) : (
            <p className="text-[12px] opacity-80">
              Контейнер {typeLabel} (детальный просмотр недоступен)
            </p>
          )}
        </div>
      </div>
    );
  }

  // Commenting: список всех привязок (multi-campaign).
  if (!links.data || links.data.length === 0) return null;

  return (
    <div className="mb-3 rounded-chip border border-hairline bg-surface-1 px-3 py-2">
      <p className="mb-1.5 text-[12px] text-text-tertiary">
        В работе в кампаниях нейрокомментинга · {links.data.length}
      </p>
      <ul className="flex flex-col gap-1">
        {links.data.map((link) => {
          const camp = campaignById.get(link.campaign_id);
          return (
            <li key={link.campaign_id}>
              <Link
                to={`/modules/commenting/campaigns/${link.campaign_id}`}
                className="flex items-center gap-2 text-[13px] text-accent hover:underline"
              >
                <Briefcase className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} aria-hidden />
                <span className="truncate">
                  {camp?.name ?? `Кампания #${link.campaign_id}`}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
