import { LayoutGrid, Megaphone } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/* Единый реестр модулей-сервисов приложения. Используется селектором «Сервисы»
   в нижнем навбаре (и может переиспользоваться где-то ещё). Навбар не растёт с
   числом модулей — новые сервисы добавляются сюда и попадают в селектор. */
export interface ModuleNavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /* Префиксы путей, на которых модуль считается активным. */
  matchPrefixes: string[];
  description?: string;
}

export const MODULES: ModuleNavItem[] = [
  {
    label: "Комментирование",
    to: "/tasks",
    icon: LayoutGrid,
    matchPrefixes: ["/tasks", "/modules/commenting"],
    description: "Кампании авто-комментирования постов",
  },
  {
    label: "НейроШиллинг",
    to: "/modules/shilling",
    icon: Megaphone,
    matchPrefixes: ["/modules/shilling"],
    description: "Нативные диалоги аккаунтов в комментариях",
  },
];

export function isModulePath(pathname: string): boolean {
  return MODULES.some((m) => m.matchPrefixes.some((p) => pathname.startsWith(p)));
}
