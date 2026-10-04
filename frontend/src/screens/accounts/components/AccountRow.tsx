import { Check, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { ageFrom, countdown, maskPhone } from "../../../shared/format";
import { CONTAINER_LABEL, PROFILE_LABEL, ROLE_LABEL } from "../../../shared/status";
import type { Account, Proxy } from "../../../shared/types";
import { StatusBadge, StatusDot } from "./ui";

/* Строка аккаунта в списке — мини-карточка (§4/§9 брифа).
 *
 * Два режима:
 *  - обычный: Link на карточку аккаунта;
 *  - выбор (selectable): чекбокс слева, клик по строке переключает выбор.
 *
 * Расширена под таблицу (этап 2): гео прокси, возраст/отлёжка, текущая задача,
 * таймер паузы/flood (cooldown_until). */
export function AccountRow({
  account,
  groupName,
  proxy,
  selectable = false,
  selected = false,
  onToggleSelect,
}: {
  account: Account;
  groupName?: string;
  proxy?: Proxy;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (id: number) => void;
}) {
  const subtitle = account.username ? `@${account.username}` : "Без юзернейма";
  const timer = countdown(account.cooldown_until);
  const task = account.assigned_container_type
    ? CONTAINER_LABEL[account.assigned_container_type] ?? account.assigned_container_type
    : "Idle";
  const roleLabel = account.role ? ROLE_LABEL[account.role] : null;

  const meta: string[] = [];
  if (proxy?.geo) meta.push(proxy.geo.toUpperCase());
  meta.push(ageFrom(account.created_at));
  meta.push(task);

  const inner = (
    <>
      {selectable ? (
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] border ${
            selected ? "border-accent bg-accent text-accent-on" : "border-strong bg-surface-1"
          }`}
          aria-hidden
        >
          {selected && <Check className="h-3.5 w-3.5" strokeWidth={2.5} />}
        </span>
      ) : (
        <StatusDot status={account.status} />
      )}

      {account.avatar_url ? (
        <img
          src={account.avatar_url}
          alt=""
          className="h-9 w-9 shrink-0 rounded-full object-cover"
        />
      ) : (
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[13px] font-semibold text-text-secondary">
          {(account.first_name ?? account.username ?? "?").slice(0, 1).toUpperCase()}
        </span>
      )}

      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-text-primary nums">
          {maskPhone(account.phone)}
        </p>
        <p className="truncate text-[13px] text-text-secondary">
          {subtitle}
          {groupName && <span className="text-text-tertiary"> · {groupName}</span>}
        </p>
        <p className="truncate text-[11px] text-text-tertiary">
          {meta.join(" · ")}
          {roleLabel && <span className="text-text-secondary"> · {roleLabel}</span>}
          {timer && <span className="text-status-warning"> · ⏳ {timer}</span>}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div className="flex flex-col items-end gap-1">
          <StatusBadge status={account.status} />
          <span className="text-[11px] text-text-tertiary">
            {PROFILE_LABEL[account.warming_profile]}
          </span>
        </div>
        {!selectable && (
          <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
        )}
      </div>
    </>
  );

  if (selectable) {
    return (
      <button
        onClick={() => onToggleSelect?.(account.id)}
        className={`card flex min-h-[64px] w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-2 ${
          selected ? "ring-1 ring-accent" : ""
        }`}
      >
        {inner}
      </button>
    );
  }

  return (
    <Link
      to={`/accounts/${account.id}`}
      className="card flex min-h-[64px] items-center gap-3 px-4 py-3 active:bg-surface-2"
    >
      {inner}
    </Link>
  );
}
