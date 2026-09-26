import { Clock, CornerUpLeft, Trash2 } from "lucide-react";
import type { Role, Step } from "../types";
import { InlineText, RoleAvatar, roleColor } from "./RoleCard";

/* Баббл одного шага в стиле мессенджера: аватар роли + текст (или эмодзи для
   реакции) + чипы (пауза, ответ на, порядок) + удаление. */
export function StepBubble({
  step,
  index,
  roles,
  roleIndex,
  onEditText,
  onDelete,
  onCyclePauseHint,
  replyTargetOrder,
  active,
  onHoverStart,
  onHoverEnd,
}: {
  step: Step;
  index: number; // 1-based порядковый номер в списке
  roles: Role[];
  roleIndex: number;
  onEditText: (text: string) => void;
  onDelete: () => void;
  onCyclePauseHint?: () => void;
  replyTargetOrder: number | null; // порядковый номер шага, на который отвечает
  active?: boolean;
  onHoverStart?: () => void;
  onHoverEnd?: () => void;
}) {
  const role = roles[roleIndex];
  const color = role ? roleColor(role, roleIndex) : "#888";
  const isReaction = step.step_type === "reaction";

  return (
    <div
      className="flex items-start gap-2"
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
    >
      <RoleAvatar name={role?.name ?? "?"} color={color} size={24} />
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex items-center gap-1.5">
          <span className="text-[11px] font-medium text-text-secondary">
            {role?.name ?? "—"}
          </span>
          <span className="text-[10px] text-text-tertiary">#{index}</span>
        </div>

        <div
          className={[
            "rounded-chip rounded-tl-sm border px-3 py-2 transition-all",
            active ? "border-accent bg-surface-2 ring-1 ring-accent" : "border-hairline bg-surface-1",
          ].join(" ")}
        >
          {isReaction ? (
            <span className="text-[20px]">{step.reaction_emoji || "👍"}</span>
          ) : (
            <InlineText
              value={step.text ?? ""}
              onCommit={onEditText}
              className="text-[14px] leading-snug text-text-primary"
              placeholder="Текст реплики…"
            />
          )}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Chip
            icon={<Clock className="h-3 w-3" strokeWidth={2} aria-hidden />}
            label={
              step.delay_before_sec != null ? `${step.delay_before_sec}с` : "пауза"
            }
            onClick={onCyclePauseHint}
          />
          {replyTargetOrder != null && (
            <Chip
              icon={<CornerUpLeft className="h-3 w-3" strokeWidth={2} aria-hidden />}
              label={`ответ на #${replyTargetOrder}`}
            />
          )}
          <button
            onClick={onDelete}
            aria-label="Удалить шаг"
            className="ml-auto text-text-tertiary active:text-status-critical"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}

function Chip({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
}) {
  const cls =
    "inline-flex items-center gap-1 rounded-pill bg-surface-2 px-2 py-0.5 text-[11px] text-text-tertiary";
  if (!onClick) return <span className={cls}>{icon}{label}</span>;
  return (
    <button type="button" onClick={onClick} className={`${cls} active:text-text-primary`}>
      {icon}
      {label}
    </button>
  );
}
