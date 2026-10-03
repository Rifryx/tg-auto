import { BellRing, Filter, LayoutGrid, MessagesSquare } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";

/* Экран «Сервисы» (мобильный таб BottomNav). Собирает все рабочие
   модули кампаний в одном месте — отдельно от служебных инструментов
   (блок «Ещё»). На десктопе этот экран тоже доступен, но там модули
   уже разложены по левой панели — так что сюда десктоп-пользователь
   редко зайдёт. */

interface Service {
  to: string;
  icon: LucideIcon;
  label: string;
  hint: string;
}

const SERVICES: Service[] = [
  {
    to: "/tasks",
    icon: LayoutGrid,
    label: "Нейрокомментинг",
    hint: "Кампании и комментарии",
  },
  {
    to: "/modules/shilling",
    icon: MessagesSquare,
    label: "НейроШиллинг",
    hint: "Сценарии посевов",
  },
  {
    to: "/modules/priming",
    icon: BellRing,
    label: "Прайминг",
    hint: "Push через системные события",
  },
  {
    to: "/modules/parsing",
    icon: Filter,
    label: "Парсинг",
    hint: "Готовые списки целей",
  },
];

export function ServicesScreen() {
  return (
    <>
      <ScreenHeader title="Сервисы" />
      <p className="mb-5 px-1 text-[13px] text-text-secondary">
        Все рабочие модули кампаний. Выберите, что запустить.
      </p>
      <div className="grid grid-cols-2 gap-2.5">
        {SERVICES.map((s) => (
          <ServiceTile key={s.to} {...s} />
        ))}
      </div>
    </>
  );
}

function ServiceTile({ to, icon: Icon, label, hint }: Service) {
  return (
    <Link
      to={to}
      className="card flex min-h-[128px] flex-col justify-between gap-3 p-4 text-left active:bg-surface-2"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-pill bg-surface-2 text-text-primary">
        <Icon className="h-[20px] w-[20px]" strokeWidth={1.8} aria-hidden />
      </span>
      <div className="min-w-0">
        <div className="text-[15px] font-semibold leading-tight text-text-primary">
          {label}
        </div>
        <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-text-tertiary">
          {hint}
        </div>
      </div>
    </Link>
  );
}
