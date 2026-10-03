import { BellRing, Filter, LayoutGrid, MessagesSquare, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";

/* Экран «Сервисы» (мобильный таб BottomNav).

   Структура:
   • «Кампании» — рабочие сервисы, запускающие активность (коммент, шиллинг,
     прайминг). Прайминг выделен как featured — главная карточка сверху
     во всю ширину с --accent-полосой слева, т.к. это самый свежий модуль
     и ключевая конверсионная поверхность.
   • «Данные» — вспомогательные (парсинг — поставщик целей для остальных).

   Каждая плитка имеет собственный tonal-акцент иконки
   (fg + подложка на accent/status-* токенах из design brief),
   чтобы ряд не читался как 4 одинаковых серых прямоугольника. */

type Tone = "accent" | "shilling" | "comment" | "parse";

interface Service {
  to: string;
  icon: LucideIcon;
  label: string;
  hint: string;
  tone: Tone;
}

const TONE_STYLES: Record<
  Tone,
  { bg: string; fg: string; dot: string }
> = {
  accent: {
    bg: "bg-accent/15",
    fg: "text-accent",
    dot: "bg-accent",
  },
  shilling: {
    bg: "bg-status-warning/15",
    fg: "text-status-warning",
    dot: "bg-status-warning",
  },
  comment: {
    bg: "bg-status-active/15",
    fg: "text-status-active",
    dot: "bg-status-active",
  },
  parse: {
    bg: "bg-status-critical/15",
    fg: "text-status-critical",
    dot: "bg-status-critical",
  },
};

const FEATURED: Service = {
  to: "/modules/priming",
  icon: BellRing,
  label: "Прайминг",
  hint: "Push через системные события — без сообщений в чате",
  tone: "accent",
};

const CAMPAIGNS: Service[] = [
  {
    to: "/tasks",
    icon: LayoutGrid,
    label: "Нейрокомментинг",
    hint: "Кампании и комментарии",
    tone: "comment",
  },
  {
    to: "/modules/shilling",
    icon: MessagesSquare,
    label: "НейроШиллинг",
    hint: "Сценарии посевов",
    tone: "shilling",
  },
];

const DATA: Service[] = [
  {
    to: "/modules/parsing",
    icon: Filter,
    label: "Парсинг",
    hint: "Готовые списки целей для прайминга и шиллинга",
    tone: "parse",
  },
];

export function ServicesScreen() {
  return (
    <>
      <ScreenHeader title="Сервисы" />
      <p className="mb-5 px-1 text-[13px] text-text-secondary">
        Все рабочие модули кампаний. Выберите, что запустить.
      </p>

      {/* Главная карточка — прайминг во всю ширину, с акцентной полосой */}
      <FeaturedTile {...FEATURED} />

      <SectionTitle>Кампании</SectionTitle>
      <div className="mb-6 grid grid-cols-2 gap-2.5">
        {CAMPAIGNS.map((s) => (
          <ServiceTile key={s.to} {...s} />
        ))}
      </div>

      <SectionTitle>Данные</SectionTitle>
      <div className="grid grid-cols-2 gap-2.5">
        {DATA.map((s) => (
          <ServiceTile key={s.to} {...s} />
        ))}
      </div>
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2.5 mt-6 px-1 text-[12px] font-semibold uppercase tracking-wide text-text-tertiary first:mt-0">
      {children}
    </h2>
  );
}

/* Крупная featured-плитка во всю ширину:
   — акцентная 3px полоса слева,
   — иконка в заметно большей подложке,
   — бейдж «новое / главный модуль». */
function FeaturedTile({ to, icon: Icon, label, hint, tone }: Service) {
  const t = TONE_STYLES[tone];
  return (
    <Link
      to={to}
      className="card relative mb-6 flex items-center gap-4 overflow-hidden p-5 active:bg-surface-2"
    >
      <span
        className={`absolute inset-y-0 left-0 w-[3px] ${t.dot}`}
        aria-hidden
      />
      <span
        className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl ${t.bg} ${t.fg}`}
      >
        <Icon className="h-7 w-7" strokeWidth={1.8} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[17px] font-semibold leading-tight text-text-primary">
            {label}
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[10px] uppercase tracking-wider ${t.bg} ${t.fg}`}
          >
            <Sparkles className="h-3 w-3" strokeWidth={2} aria-hidden />
            Новое
          </span>
        </div>
        <p className="mt-1 text-[12px] leading-snug text-text-tertiary">
          {hint}
        </p>
      </div>
    </Link>
  );
}

/* Обычная плитка — иконка с tonal-подложкой, подпись + подсказка. */
function ServiceTile({ to, icon: Icon, label, hint, tone }: Service) {
  const t = TONE_STYLES[tone];
  return (
    <Link
      to={to}
      className="card flex min-h-[128px] flex-col justify-between gap-3 p-4 text-left active:bg-surface-2"
    >
      <span
        className={`flex h-10 w-10 items-center justify-center rounded-pill ${t.bg} ${t.fg}`}
      >
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
