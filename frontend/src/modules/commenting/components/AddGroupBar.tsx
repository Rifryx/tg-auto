import { useState } from "react";
import { Select } from "../../../shared/Select";
import { haptic } from "../../../shared/tg";
import type { Account } from "../../../shared/types";
import { CapsuleButton } from "./ui";

/* Кнопка «Добавить группу аккаунтов целиком».
 *
 * Кампания эксклюзивно занимает аккаунт: одновременно взять его могут
 * только те, кто сейчас в пуле. Поэтому кнопка добавляет только free.
 * Занятые (прогрев, другая кампания, cooldown) показываем счётчиком,
 * чтобы пользователь понимал, почему добавилось меньше, чем в группе.
 *
 * `onAdd` получает id уже отфильтрованных «свободных» аккаунтов и сам
 * решает, что с ними делать (у new campaign — Set state, у detail —
 * массовый attach).
 */
export function AddGroupBar({
  groups,
  pool,
  all,
  onAdd,
  actionLabelPending,
}: {
  groups: { id: number; name: string }[];
  pool: Account[];
  all: Account[];
  onAdd: (ids: number[]) => void;
  actionLabelPending?: string;
}) {
  const [groupId, setGroupId] = useState<string>("");
  if (groups.length === 0) return null;

  const gid = groupId ? Number(groupId) : null;
  const free = gid == null ? [] : pool.filter((a) => a.project_id === gid);
  const total = gid == null ? 0 : all.filter((a) => a.project_id === gid).length;
  const busy = total - free.length;

  return (
    <div className="mb-4 rounded-chip border border-hairline bg-surface-1 p-3">
      <p className="mb-2 px-1 text-[13px] text-text-tertiary">
        Добавить группу аккаунтов целиком
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Select
          className="sm:flex-1"
          value={groupId}
          onChange={setGroupId}
          placeholder="Выберите группу"
          options={groups.map((g) => ({ value: String(g.id), label: g.name }))}
        />
        <CapsuleButton
          variant={free.length > 0 && !actionLabelPending ? "accent" : "secondary"}
          disabled={free.length === 0 || !!actionLabelPending}
          onClick={() => {
            haptic("light");
            onAdd(free.map((a) => a.id));
          }}
          className="sm:w-auto sm:shrink-0"
        >
          {actionLabelPending
            ? actionLabelPending
            : gid == null
              ? "Добавить группу"
              : `Добавить ${free.length}`}
        </CapsuleButton>
      </div>
      {gid != null && (
        <p className="mt-2 px-1 text-[12px] text-text-tertiary">
          {total === 0
            ? "В группе пока нет аккаунтов — добавьте их в «Группы аккаунтов»."
            : busy > 0
              ? `Свободно ${free.length} из ${total}. Ещё ${busy} ${busy === 1 ? "занят" : "заняты"} (прогрев, другая кампания или отдых) — кампания может взять только свободные.`
              : `Все ${total} аккаунтов группы свободны.`}
        </p>
      )}
    </div>
  );
}
