import { useEffect, useState } from "react";
import { Pencil, X } from "lucide-react";
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

/* Карточка роли: аватар + имя/характер + правка + удаление.
   Клик по карточке ВЫБИРАЕТ роль активной (selected/onSelect) — новые шаги
   диалога добавляются от её лица. Правка имени/характера — по кнопке-карандашу
   (чтобы клик по тексту не мешал выбору роли). */
export function RoleCard({
  role,
  index,
  selected,
  onSelect,
  onRename,
  onCharacter,
  onDelete,
}: {
  role: Role;
  index: number;
  selected?: boolean;
  onSelect?: () => void;
  onRename: (name: string) => void;
  onCharacter: (character: string) => void;
  onDelete: () => void;
}) {
  const color = roleColor(role, index);
  const [editing, setEditing] = useState(false);
  return (
    <div
      onClick={onSelect}
      role={onSelect ? "button" : undefined}
      aria-pressed={onSelect ? !!selected : undefined}
      className={[
        "card flex items-start gap-2.5 p-3 transition-all",
        onSelect && !editing ? "cursor-pointer" : "",
        selected ? "border-accent ring-1 ring-accent" : "",
      ].join(" ")}
    >
      <RoleAvatar name={role.name} color={color} />
      {editing ? (
        <div className="min-w-0 flex-1" onClick={(e) => e.stopPropagation()}>
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
      ) : (
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold text-text-primary">{role.name}</p>
          <p className={`truncate text-[12px] ${role.character ? "text-text-tertiary" : "text-text-tertiary/70"}`}>
            {role.character || "Характер, стиль речи"}
          </p>
        </div>
      )}
      {selected && (
        <span className="shrink-0 self-center rounded-pill bg-accent px-2 py-0.5 text-[10px] font-semibold text-accent-on">
          активна
        </span>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          setEditing((v) => !v);
        }}
        aria-label={editing ? "Готово" : "Редактировать роль"}
        className={`shrink-0 self-start ${editing ? "text-accent" : "text-text-tertiary"} active:text-text-primary`}
      >
        <Pencil className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Удалить роль"
        className="shrink-0 self-start text-text-tertiary active:text-status-critical"
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
