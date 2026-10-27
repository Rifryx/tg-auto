import { useState } from "react";
import { Select } from "../../../shared/Select";
import { haptic } from "../../../shared/tg";
import type { Account } from "../../../shared/types";
import { CapsuleButton } from "./ui";

/* Массовые действия над группой аккаунтов (целиком).
 *
 * Теперь поддерживаются ДВА режима: «добавить группу» и «убрать группу».
 * Первое отдаёт id свободных для прикрепления (не banned/retired, не в этой
 * кампании уже) — после изменения state machine attach работает из любого
 * рабочего статуса, warming/cooldown прервутся. Второе отдаёт id тех
 * аккаунтов группы, которые СЕЙЧАС прикреплены к кампании (чтобы их все
 * одной кнопкой отвязать).
 *
 * `attachedIds` — опционально. Если передан, рисуем вторую строку
 * «Убрать всю группу» для той же группы.
 */
export function AddGroupBar({
  groups,
  all,
  onAdd,
  attachedIds,
  onRemove,
  actionLabelPending,
  removeLabelPending,
}: {
  groups: { id: number; name: string }[];
  /** Все аккаунты (без фильтра по статусу). Из них компонент сам возьмёт
   *  attach-ready (status !== banned/retired). */
  all: Account[];
  onAdd: (ids: number[]) => void;
  /** Если передан — показываем кнопку «Убрать группу». */
  attachedIds?: number[];
  onRemove?: (ids: number[]) => void;
  actionLabelPending?: string;
  removeLabelPending?: string;
}) {
  const [groupId, setGroupId] = useState<string>("");
  if (groups.length === 0) return null;

  const gid = groupId ? Number(groupId) : null;
  const inGroup = gid == null ? [] : all.filter((a) => a.project_id === gid);
  // Attach-ready: не забанен и не выведен. Остальное state machine разберёт.
  const attachable = inGroup.filter(
    (a) => a.status !== "banned" && a.status !== "retired",
  );
  // Для «не из группы» показываем сколько реально невозможно прикрепить.
  const unusable = inGroup.length - attachable.length;
  const attachedSet = new Set(attachedIds ?? []);
  const toAdd = attachable.filter((a) => !attachedSet.has(a.id));
  const toRemove = attachable.filter((a) => attachedSet.has(a.id));

  return (
    <div className="mb-4 rounded-chip border border-hairline bg-surface-1 p-3">
      <p className="mb-2 px-1 text-[13px] text-text-tertiary">
        {attachedIds ? "Группа аккаунтов целиком" : "Добавить группу аккаунтов целиком"}
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
          variant={toAdd.length > 0 && !actionLabelPending ? "accent" : "secondary"}
          disabled={toAdd.length === 0 || !!actionLabelPending}
          onClick={() => {
            haptic("light");
            onAdd(toAdd.map((a) => a.id));
          }}
          className="sm:w-auto sm:shrink-0"
        >
          {actionLabelPending
            ? actionLabelPending
            : gid == null
              ? "Добавить группу"
              : `Добавить ${toAdd.length}`}
        </CapsuleButton>
      </div>
      {attachedIds && onRemove && (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <CapsuleButton
            variant="secondary"
            disabled={toRemove.length === 0 || !!removeLabelPending}
            onClick={() => {
              haptic("light");
              onRemove(toRemove.map((a) => a.id));
            }}
            className="sm:w-auto sm:shrink-0"
          >
            {removeLabelPending
              ? removeLabelPending
              : gid == null
                ? "Убрать группу"
                : `Убрать ${toRemove.length}`}
          </CapsuleButton>
        </div>
      )}
      {gid != null && (
        <p className="mt-2 px-1 text-[12px] text-text-tertiary">
          {inGroup.length === 0
            ? "В группе пока нет аккаунтов — добавьте их в «Группы аккаунтов»."
            : unusable > 0
              ? `В группе ${inGroup.length}. Можно использовать ${attachable.length} (${unusable} ${unusable === 1 ? "забанен / выведен" : "забанены / выведены"}).`
              : `В группе ${inGroup.length} аккаунтов.`}
          {attachedIds && toRemove.length > 0 && (
            <> Сейчас в этой кампании: {toRemove.length}.</>
          )}
        </p>
      )}
    </div>
  );
}
