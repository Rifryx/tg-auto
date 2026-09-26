import { Clock, CornerUpLeft, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Role, Step } from "../types";
import { REACTIONS } from "../reactions";
import { InlineText, RoleAvatar, roleColor } from "./RoleCard";

/* Баббл одного шага в стиле мессенджера: аватар роли + текст (или эмодзи для
   реакции) + чипы (пауза, ответ на, порядок) + удаление. Аватар/имя кликаются
   для смены роли шага; реакция — для выбора эмодзи из коллекции. */
export function StepBubble({
  step,
  index,
  roles,
  roleIndex,
  onEditText,
  onDelete,
  onChangeRole,
  onChangeReaction,
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
  onChangeRole?: (roleId: number) => void;
  onChangeReaction?: (emoji: string) => void;
  onCyclePauseHint?: () => void;
  replyTargetOrder: number | null; // порядковый номер шага, на который отвечает
  active?: boolean;
  onHoverStart?: () => void;
  onHoverEnd?: () => void;
}) {
  const role = roles[roleIndex];
  const color = role ? roleColor(role, roleIndex) : "#888";
  const isReaction = step.step_type === "reaction";
  const [roleMenu, setRoleMenu] = useState(false);
  const [reactionMenu, setReactionMenu] = useState(false);

  return (
    <div
      className="flex items-start gap-2"
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
    >
      {/* Аватар роли — клик открывает выбор роли шага */}
      <div className="relative">
        <button
          type="button"
          onClick={() => onChangeRole && roles.length > 1 && setRoleMenu((v) => !v)}
          aria-label="Сменить роль шага"
          className={onChangeRole && roles.length > 1 ? "cursor-pointer" : "cursor-default"}
        >
          <RoleAvatar name={role?.name ?? "?"} color={color} size={24} />
        </button>
        {roleMenu && (
          <Popover onClose={() => setRoleMenu(false)}>
            <p className="px-2 pb-1 pt-0.5 text-[11px] text-text-tertiary">Роль шага</p>
            {roles.map((r, i) => (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  onChangeRole?.(r.id);
                  setRoleMenu(false);
                }}
                className="flex w-full items-center gap-2 rounded-chip px-2 py-1.5 text-left text-[13px] text-text-primary active:bg-surface-2"
              >
                <RoleAvatar name={r.name} color={roleColor(r, i)} size={20} />
                <span className="truncate">{r.name}</span>
                {r.id === step.role_id && (
                  <span className="ml-auto text-[11px] text-text-tertiary">текущая</span>
                )}
              </button>
            ))}
          </Popover>
        )}
      </div>

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
            <div className="relative inline-block">
              <button
                type="button"
                onClick={() => onChangeReaction && setReactionMenu((v) => !v)}
                className="text-[20px] leading-none active:opacity-70"
                aria-label="Выбрать реакцию"
              >
                {step.reaction_emoji || "👍"}
              </button>
              {reactionMenu && (
                <Popover onClose={() => setReactionMenu(false)} wide>
                  <div className="grid grid-cols-8 gap-0.5">
                    {REACTIONS.map((emoji) => (
                      <button
                        key={emoji}
                        type="button"
                        onClick={() => {
                          onChangeReaction?.(emoji);
                          setReactionMenu(false);
                        }}
                        className={[
                          "flex h-8 w-8 items-center justify-center rounded-chip text-[18px] active:bg-surface-2",
                          step.reaction_emoji === emoji ? "bg-surface-2 ring-1 ring-accent" : "",
                        ].join(" ")}
                      >
                        {emoji}
                      </button>
                    ))}
                  </div>
                </Popover>
              )}
            </div>
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

/* Небольшой поповер с закрытием по клику вне/Escape. */
function Popover({
  children,
  onClose,
  wide,
}: {
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  return (
    <div
      ref={ref}
      className={[
        "absolute left-0 top-full z-20 mt-1 rounded-card border border-hairline bg-bg-elevated p-1.5 shadow-lg",
        wide ? "w-[292px]" : "w-44",
      ].join(" ")}
    >
      {children}
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
