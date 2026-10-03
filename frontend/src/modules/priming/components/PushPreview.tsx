import { Lock } from "lucide-react";
import type { PrimingTriggerAction } from "../types";

/* Preview lock-screen push (docs/priming-ui.md §5.1, §9.1).
   Уникальная фича — конкурент не показывает, что реально увидит цель. */

const PUSH_TEXT: Record<PrimingTriggerAction, string> = {
  set_ttl_1d: "{{name}} включил автоудаление сообщений",
  set_ttl_off: "{{name}} выключил автоудаление сообщений",
  set_content_protection: "{{name}} запретил копирование сообщений",
  secret_chat_request: "{{name}} пригласил вас в секретный чат",
  contact_added: "{{name}} добавил вас в контакты",
  contact_removed: "{{name}} убрал вас из контактов",
  pinned_message_ping: "{{name}} закрепил сообщение",
};

interface Props {
  action: PrimingTriggerAction;
  actorName?: string;
}

/* Карточка `--surface-2` + hairline + левая полоса-акцент 3px
   (`--surface-border-strong`). Никаких iOS-скинов кнопок Answer/Decline. */
export function PushPreview({ action, actorName }: Props) {
  const raw = PUSH_TEXT[action];
  const name = actorName || "Александр";
  const body = raw.replace("{{name}}", name);
  return (
    <div className="rounded-2xl border border-hairline bg-surface-2 p-4">
      <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-wider text-text-tertiary">
        <Lock className="h-3 w-3" strokeWidth={2} aria-hidden />
        Экран блокировки · сейчас
      </div>
      <div className="border-l-[3px] border-white/20 pl-3">
        <p className="text-[13px] font-medium text-text-secondary">Telegram</p>
        <p className="mt-0.5 text-[15px] text-text-primary">{body}</p>
      </div>
    </div>
  );
}
