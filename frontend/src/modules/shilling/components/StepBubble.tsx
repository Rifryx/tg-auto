import { Check, ChevronDown, Clock, CornerUpLeft, GripVertical, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Role, Step } from "../types";
import { InlineText, RoleAvatar, roleColor } from "./RoleCard";

/* Цель ответа: на какой шаг отвечает текущий (для цитаты над текстом). */
export interface ReplyTarget {
  order: number; // 1-based номер шага-цели
  roleName: string;
  color: string;
  preview: string; // короткий текст/эмодзи цели
}

/* Кандидат для пикера «ответить на…»: более ранний шаг. */
export interface ReplyOption {
  stepId: number;
  order: number;
  roleName: string;
  color: string;
  preview: string;
}

/* Баббл одного шага в стиле мессенджера: аватар роли + текст (или эмодзи для
   реакции) + цитата ответа + чипы + действия (ответить / удалить / перетащить).

   Роль (персона) шага выбирается через отдельный пикер в шапке баббла. */
export function StepBubble({
  step,
  index,
  roles,
  roleIndex,
  onEditText,
  onChangeRole,
  onDelete,
  onCyclePauseHint,
  replyTarget,
  replyOptions,
  onSetReply,
  active,
  onHoverStart,
  onHoverEnd,
  // drag
  dragging,
  dropTarget,
  onDragStartRow,
  onDragEnterRow,
  onDragEndRow,
}: {
  step: Step;
  index: number; // 1-based порядковый номер в списке
  roles: Role[];
  roleIndex: number;
  onEditText: (text: string) => void;
  onChangeRole: (roleId: number) => void;
  onDelete: () => void;
  onCyclePauseHint?: () => void;
  replyTarget: ReplyTarget | null;
  replyOptions: ReplyOption[]; // более ранние шаги, на которые можно ответить
  onSetReply: (targetStepId: number | null) => void;
  active?: boolean;
  onHoverStart?: () => void;
  onHoverEnd?: () => void;
  dragging?: boolean;
  dropTarget?: boolean;
  onDragStartRow?: () => void;
  onDragEnterRow?: () => void;
  onDragEndRow?: () => void;
}) {
  const role = roles[roleIndex];
  const isReaction = step.step_type === "reaction";
  // Перетаскивание разрешаем ТОЛЬКО когда зажата ручка — иначе HTML5-draggable
  // на всём ряду ломает выделение и правку текста в реплике.
  const [dragEnabled, setDragEnabled] = useState(false);

  return (
    <div
      draggable={dragEnabled}
      onDragStart={(e) => {
        if (!dragEnabled) {
          e.preventDefault();
          return;
        }
        e.dataTransfer.effectAllowed = "move";
        onDragStartRow?.();
      }}
      onDragEnter={onDragEnterRow}
      onDragOver={(e) => e.preventDefault()}
      onDragEnd={() => {
        setDragEnabled(false);
        onDragEndRow?.();
      }}
      className={[
        "flex items-start gap-2 rounded-chip transition-all",
        dragging ? "opacity-40" : "",
        dropTarget ? "ring-1 ring-accent ring-offset-2 ring-offset-bg-base" : "",
      ].join(" ")}
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

          {/* Действия справа: ответить / удалить / перетащить. */}
          <div className="ml-auto flex items-center gap-0.5">
            <ReplyPicker
              hasReply={replyTarget != null}
              options={replyOptions}
              onSetReply={onSetReply}
            />
            <button
              onClick={onDelete}
              aria-label="Удалить шаг"
              className="flex h-6 w-6 items-center justify-center rounded-md text-text-tertiary hover:bg-surface-2 active:text-status-critical"
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
            </button>
            {/* Ручка перетаскивания: зажать и тянуть, чтобы поменять порядок. */}
            <button
              type="button"
              aria-label="Перетащить шаг"
              title="Перетащить, чтобы изменить порядок"
              onMouseDown={() => setDragEnabled(true)}
              onMouseUp={() => setDragEnabled(false)}
              onTouchStart={() => setDragEnabled(true)}
              className="flex h-6 w-6 cursor-grab items-center justify-center rounded-md text-text-tertiary hover:bg-surface-2 active:cursor-grabbing"
            >
              <GripVertical className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
            </button>
          </div>
        </div>

        {/* Цитата ответа над текстом (как в Telegram). */}
        {replyTarget != null && (
          <div className="mb-1 flex items-start gap-1.5 rounded-chip rounded-bl-sm border-l-[3px] bg-surface-2 py-1 pl-2 pr-1.5"
            style={{ borderLeftColor: replyTarget.color }}
          >
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold" style={{ color: replyTarget.color }}>
                {replyTarget.roleName}
                <span className="ml-1 font-normal text-text-tertiary">#{replyTarget.order}</span>
              </p>
              <p className="truncate text-[12px] text-text-secondary">{replyTarget.preview}</p>
            </div>
            <button
              onClick={() => onSetReply(null)}
              aria-label="Убрать ответ"
              className="shrink-0 text-text-tertiary hover:text-status-critical"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
            </button>
          </div>
        )}

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
        </div>
      </div>
    </div>
  );
}

/* Кнопка-стрелка «ответить на…». По клику — список более ранних шагов (ответить
   можно только на то, что УЖЕ было сказано — иначе в рантайме отвечать не на
   что) + пункт «Просто отправка» (убрать ответ). */
function ReplyPicker({
  hasReply,
  options,
  onSetReply,
}: {
  hasReply: boolean;
  options: ReplyOption[];
  onSetReply: (targetStepId: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-label={hasReply ? "Изменить ответ" : "Ответить на сообщение"}
        title={hasReply ? "Изменить ответ" : "Ответить на сообщение"}
        onClick={() => {
          // Нет ранних шагов — отвечать не на что, не открываем пустой список.
          if (options.length === 0) return;
          setOpen((v) => !v);
        }}
        disabled={options.length === 0 && !hasReply}
        className={[
          "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
          hasReply
            ? "bg-accent/15 text-accent"
            : "text-text-tertiary hover:bg-surface-2 disabled:opacity-40",
        ].join(" ")}
      >
        <CornerUpLeft className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+4px)] z-30 w-56 overflow-hidden rounded-chip border border-hairline bg-bg-elevated py-1 shadow-lg">
          <p className="px-2.5 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
            Ответить на реплику
          </p>
          {options.map((o) => (
            <button
              key={o.stepId}
              type="button"
              onClick={() => {
                onSetReply(o.stepId);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] text-text-secondary active:bg-surface-1"
            >
              <RoleAvatar name={o.roleName} color={o.color} size={18} />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-text-primary">#{o.order}</span>{" "}
                <span className="text-text-tertiary">{truncate(o.preview, 24)}</span>
              </span>
            </button>
          ))}
          <div className="my-1 border-t border-hairline" />
          <button
            type="button"
            onClick={() => {
              onSetReply(null);
              setOpen(false);
            }}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] text-text-secondary active:bg-surface-1"
          >
            <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full bg-surface-2 text-text-tertiary">
              <X className="h-3 w-3" strokeWidth={2} aria-hidden />
            </span>
            Просто отправка (без ответа)
          </button>
        </div>
      )}
    </div>
  );
}

/* Пикер роли шага: аватар (+ стрелка, если ролей несколько). */
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
                className={[
                  "flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]",
                  selected
                    ? "bg-surface-2 font-semibold text-text-primary"
                    : "text-text-secondary active:bg-surface-1",
                ].join(" ")}
              >
                <RoleAvatar name={r.name} color={roleColor(r, i)} size={20} />
                <span className="min-w-0 flex-1 truncate">{r.name || `Роль ${i + 1}`}</span>
                {selected && (
                  <Check className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={2.5} aria-hidden />
                )}
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

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
