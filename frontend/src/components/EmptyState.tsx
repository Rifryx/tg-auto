import type { LucideIcon } from "lucide-react";

/* Пустое состояние экрана-заглушки (§4/§9 брифа + принцип «пустой экран — это
   приглашение к действию»): монохромная line-иконка + направляющая подпись,
   не белый лист. */
export function EmptyState({
  icon: Icon,
  title,
  hint,
}: {
  icon: LucideIcon;
  title: string;
  hint: string;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center">
      <Icon
        className="mb-4 h-10 w-10 text-text-tertiary"
        strokeWidth={1.5}
        aria-hidden
      />
      <p className="text-[15px] font-medium text-text-secondary">{title}</p>
      <p className="mt-1 max-w-[240px] text-[13px] text-text-tertiary">{hint}</p>
    </div>
  );
}
