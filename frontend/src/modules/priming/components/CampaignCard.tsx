import { BellRing, ChevronRight } from "lucide-react";
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

export function CampaignCard({ campaign }: { campaign: PrimingCampaign }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(`/modules/priming/campaigns/${campaign.id}`)}
      className="card flex w-full items-center gap-4 p-4 text-left active:bg-surface-2"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <BellRing className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <StatusDot status={campaign.status} />
          <span className="truncate text-[15px] font-semibold leading-tight text-text-primary">
            {campaign.name}
          </span>
          {campaign.dry_run && (
            <span
              className="ml-1 shrink-0 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-text-secondary"
              aria-label="Тестовый прогон, без реальных Push"
            >
              dry-run
            </span>
          )}
        </div>
        <p className="mt-0.5 truncate text-[13px] text-text-tertiary">
          {STATUS_LABEL[campaign.status]} · {TRIGGER_LABEL[campaign.trigger_action]}
        </p>
        <p className="mt-0.5 text-[12px] text-text-tertiary">
          {timeAgo(campaign.updated_at)}
        </p>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </button>
  );
}
