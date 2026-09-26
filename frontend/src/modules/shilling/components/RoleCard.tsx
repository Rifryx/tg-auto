import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { Role } from "../types";

/* Палитра аватарок ролей — детерминированно по индексу/цвету роли.
   Это не тема-токены (аватарки одинаковы в обеих темах), поэтому hex-строки. */
const PALETTE = [
  "#f87171", // red
  "#fbbf24", // amber
  "#34d399", // emerald
  "#60a5fa", // blue
  "#a78bfa", // violet
  "#f472b6", // pink
  "#22d3ee", // cyan
  "#a3e635", // lime
];

export function roleColor(role: Pick<Role, "id" | "color">, index: number): string {
  if (role.color) return role.color;
  return PALETTE[index % PALETTE.length];
}

export function RoleAvatar({
  name,
  color,
  size = 28,
}: {
  name: string;
  color: string;
  size?: number;
}) {
  const letter = (name.trim()[0] || "?").toUpperCase();
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{ background: color, width: size, height: size, fontSize: size * 0.45 }}
      aria-hidden
    >
      {letter}
    </span>
  );
}

/* Карточка роли: аватар + inline-редактируемые имя и характер + удаление. */
export function RoleCard({
  role,
  index,
  onRename,
  onCharacter,
  onDelete,
}: {
  role: Role;
  index: number;
  onRename: (name: string) => void;
  onCharacter: (character: string) => void;
  onDelete: () => void;
}) {
  const color = roleColor(role, index);
  return (
    <div className="card flex items-start gap-2.5 p-3">
      <RoleAvatar name={role.name} color={color} />
      <div className="min-w-0 flex-1">
        <InlineText
          value={role.name}
          onCommit={onRename}
          className="text-[14px] font-semibold text-text-primary"
          placeholder="Роль"
        />
        <InlineText
          value={role.character ?? ""}
          onCommit={onCharacter}
          className="text-[12px] text-text-tertiary"
          placeholder="Характер, стиль речи"
        />
      </div>
      <button
        onClick={onDelete}
        aria-label="Удалить роль"
        className="shrink-0 text-text-tertiary active:text-status-critical"
      >
        <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </button>
    </div>
  );
}

/* Инлайн-поле: правка по клику, сохранение onBlur/Enter, откат по Escape. */
export function InlineText({
  value,
  onCommit,
  className,
  placeholder,
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
  placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          if (draft.trim() !== value.trim()) onCommit(draft.trim());
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        placeholder={placeholder}
        className={`w-full rounded-[6px] bg-surface-1 px-1.5 py-0.5 outline-none ring-1 ring-accent ${className ?? ""}`}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className={`block w-full truncate text-left ${className ?? ""} ${
        !value ? "text-text-tertiary" : ""
      }`}
    >
      {value || placeholder}
    </button>
  );
}
