import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { timeAgo } from "../../../shared/format";
import type { PrimingCampaign, PrimingCampaignStatus } from "../types";
import { StatusDot } from "./StatusDot";

const STATUS_LABEL: Record<PrimingCampaignStatus, string> = {
  draft: "Черновик",
  queued: "В очереди",
  running: "Идёт",
  paused: "Пауза",
  stopped: "Остановлена",
  finished: "Завершена",
  failed: "Ошибка",
};

const TRIGGER_LABEL: Record<PrimingCampaign["trigger_action"], string> = {
  set_ttl_1d: "Автоудаление",
  set_ttl_off: "Автоудаление ⛔",
  set_content_protection: "Запрет копирования",
  secret_chat_request: "Секретный чат",
  contact_added: "Добавили в контакты",
  contact_removed: "Убрали из контактов",
  pinned_message_ping: "Закреплённое сообщение",
};

/* Карточка кампании в списке (UI бриф §5, priming-ui §4).
   Никаких shadow / gradient — фон surface-1 + hairline через .card. */
export function CampaignCard({ campaign }: { campaign: PrimingCampaign }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(`/modules/priming/campaigns/${campaign.id}`)}
      className="card w-full p-4 text-left active:opacity-80"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusDot status={campaign.status} />
            <h3 className="truncate text-[17px] font-semibold text-text-primary">
              {campaign.name}
            </h3>
            {campaign.dry_run && (
              <span
                className="ml-1 shrink-0 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-text-secondary"
                aria-label="Тестовый прогон, без реальных Push"
              >
                dry-run
              </span>
            )}
          </div>
          <p className="mt-1 truncate text-[13px] text-text-secondary">
            {STATUS_LABEL[campaign.status]} · {TRIGGER_LABEL[campaign.trigger_action]}
          </p>
          <p className="mt-0.5 text-[12px] text-text-tertiary">
            Обновлено {timeAgo(campaign.updated_at)}
          </p>
        </div>
        <ArrowRight
          className="mt-1 h-4 w-4 shrink-0 text-text-tertiary"
          strokeWidth={2}
          aria-hidden
        />
      </div>
    </button>
  );
}
