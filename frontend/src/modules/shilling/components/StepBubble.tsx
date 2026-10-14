import { Check, ChevronDown, Clock, CornerUpLeft, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Role, Step } from "../types";
import { InlineText, RoleAvatar, roleColor } from "./RoleCard";

/* Баббл одного шага в стиле мессенджера: аватар роли + текст (или эмодзи для
   реакции) + чипы (пауза, ответ на, порядок) + удаление.

   Роль (персона) шага выбирается через отдельный пикер в шапке баббла — это
   единственный способ сменить персону, и он намеренно отделён от inline-правки
   имени роли в списке «Роли», чтобы не было мисклика в редактирование. */
export function StepBubble({
  step,
  index,
  roles,
  roleIndex,
  onEditText,
  onChangeRole,
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
  onChangeRole: (roleId: number) => void;
  onDelete: () => void;
  onCyclePauseHint?: () => void;
  replyTargetOrder: number | null; // порядковый номер шага, на который отвечает
  active?: boolean;
  onHoverStart?: () => void;
  onHoverEnd?: () => void;
}) {
  const role = roles[roleIndex];
  const isReaction = step.step_type === "reaction";

  return (
    <div
      className="flex items-start gap-2"
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
    >
      <RolePicker
        roles={roles}
        currentRoleId={step.role_id}
        onChange={onChangeRole}
        avatarSize={24}
      />
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

/* Пикер роли шага: аватар (+ стрелка, если ролей несколько). По клику —
   выпадающий список ролей; выбор меняет персону шага. При одной роли это просто
   аватар без действия. */
function RolePicker({
  roles,
  currentRoleId,
  onChange,
  avatarSize = 24,
}: {
  roles: Role[];
  currentRoleId: number;
  onChange: (roleId: number) => void;
  avatarSize?: number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const currentIndex = roles.findIndex((r) => r.id === currentRoleId);
  const current = roles[currentIndex];
  const color = current ? roleColor(current, currentIndex) : "#888";
  const multiple = roles.length > 1;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => multiple && setOpen((v) => !v)}
        disabled={!multiple}
        aria-label={multiple ? "Сменить персону шага" : current?.name}
        className={`relative flex items-center ${multiple ? "active:opacity-80" : "cursor-default"}`}
      >
        <RoleAvatar name={current?.name ?? "?"} color={color} size={avatarSize} />
        {multiple && (
          <span className="absolute -bottom-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full border border-bg-base bg-surface-2 text-text-secondary">
            <ChevronDown className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-30 w-44 overflow-hidden rounded-chip border border-hairline bg-bg-elevated py-1 shadow-lg">
          {roles.map((r, i) => {
            const selected = r.id === currentRoleId;
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  if (!selected) onChange(r.id);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px] text-text-primary active:bg-surface-2"
              >
                <RoleAvatar name={r.name} color={roleColor(r, i)} size={20} />
                <span className="min-w-0 flex-1 truncate">{r.name || `Роль ${i + 1}`}</span>
                {selected && <Check className="h-3.5 w-3.5 text-accent" strokeWidth={2.5} aria-hidden />}
              </button>
            );
          })}
        </div>
      )}
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
