import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Play, Power, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ACTION_LABEL,
  autopilotApi,
  GOAL_DESCRIPTION,
  GOAL_LABEL,
  GOAL_PARAM_KEY,
  type Goal,
  type GoalType,
} from "../../shared/autopilot";
import { timeAgo } from "../../shared/format";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  Section,
  TextInput,
} from "../../modules/commenting/components/ui";
import { BackHeader } from "./PersonasScreen";

/* Экран Autopilot (этап 13, UI для этапа 12):
 *
 *   ┌─ Новая цель ────────────────────┐
 *   │ [Держать в пуле ▾] [20] [Добавить] │
 *   └─────────────────────────────────┘
 *   ┌─ Активные цели ─────────────────┐
 *   │ ● Держать в пуле = 20        [⏻][✕] │
 *   │ ○ Низкий риск бана < 0.3     [⏻][✕] │
 *   └─────────────────────────────────┘
 *   ┌─ Журнал решений (20 последних) ─┐
 *   │ 12:03 · start_warming · #42 · "pool deficit…" │
 *   └─────────────────────────────────┘
 *
 * Автопилот выполняет действия в фоне (cron 10 мин). Экран — только
 * управление целями и наблюдение за журналом.
 */

const GOAL_TYPES: GoalType[] = [
  "maintain_pool_size",
  "keep_low_risk",
  "warmup_pipeline",
];

const DEFAULT_VALUE: Record<GoalType, number> = {
  maintain_pool_size: 20,
  keep_low_risk: 0.3,
  warmup_pipeline: 5,
};

export function AutopilotScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [goalType, setGoalType] = useState<GoalType>("maintain_pool_size");
  const [rawValue, setRawValue] = useState<string>(
    String(DEFAULT_VALUE[goalType]),
  );
  const [toDelete, setToDelete] = useState<Goal | null>(null);

  const status = useQuery({
    queryKey: ["autopilot", "status"],
    queryFn: autopilotApi.status,
    refetchInterval: 15_000,
  });

  const create = useMutation({
    mutationFn: () => {
      const key = GOAL_PARAM_KEY[goalType];
      const num = Number(rawValue);
      return autopilotApi.createGoal({
        goal_type: goalType,
        params: { [key]: num },
      });
    },
    onSuccess: () => {
      setRawValue(String(DEFAULT_VALUE[goalType]));
      qc.invalidateQueries({ queryKey: ["autopilot", "status"] });
    },
  });

  const toggle = useMutation({
    mutationFn: (goal: Goal) =>
      autopilotApi.updateGoal(goal.id, { enabled: !goal.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["autopilot", "status"] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => autopilotApi.deleteGoal(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["autopilot", "status"] });
    },
  });

  const parsedValue = Number(rawValue);
  const validValue =
    !Number.isNaN(parsedValue) &&
    parsedValue > 0 &&
    (goalType !== "keep_low_risk" || parsedValue <= 1);

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Автопилот" onBack={() => navigate("/more")} />

      <Section title="Новая цель">
        <div className="card flex flex-col gap-4 p-4">
          <Field label="Тип цели">
            <select
              value={goalType}
              onChange={(e) => {
                const t = e.target.value as GoalType;
                setGoalType(t);
                setRawValue(String(DEFAULT_VALUE[t]));
              }}
              className="w-full rounded-xl border border-hairline bg-surface-1 px-3 py-2 text-[15px] text-text-primary outline-none"
            >
              {GOAL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {GOAL_LABEL[t]}
                </option>
              ))}
            </select>
          </Field>
          <p className="text-[12px] text-text-tertiary">
            {GOAL_DESCRIPTION[goalType]}
          </p>
          <Field
            label={
              goalType === "keep_low_risk"
                ? "Максимальный средний риск (0.0–1.0)"
                : "Целевое количество"
            }
          >
            <TextInput
              type="number"
              value={rawValue}
              step={goalType === "keep_low_risk" ? "0.05" : "1"}
              min={goalType === "keep_low_risk" ? "0" : "1"}
              max={goalType === "keep_low_risk" ? "1" : undefined}
              onChange={(e) => setRawValue(e.target.value)}
            />
          </Field>
          <CapsuleButton
            variant={validValue ? "accent" : "secondary"}
            disabled={!validValue || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Добавляем…" : "Добавить цель"}
          </CapsuleButton>
        </div>
      </Section>

      <Section title={`Цели (${status.data?.goals.length ?? 0})`}>
        {status.data && status.data.goals.length > 0 ? (
          <div className="flex flex-col gap-2">
            {status.data.goals.map((g) => (
              <GoalRow
                key={g.id}
                goal={g}
                onToggle={() => toggle.mutate(g)}
                onDelete={() => setToDelete(g)}
              />
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">
            Цели ещё не заданы. Автопилот не будет ничего делать, пока не появится
            хотя бы одна включённая цель.
          </p>
        )}
      </Section>

      <Section title="Последние решения">
        {status.data && status.data.recent_actions.length > 0 ? (
          <div className="card overflow-hidden p-0">
            {status.data.recent_actions.map((a, i) => (
              <div
                key={a.id}
                className={
                  "flex items-start gap-3 px-4 py-3 " +
                  (i > 0 ? "border-t border-hairline" : "")
                }
              >
                <StatusDot status={a.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[14px] text-text-primary">
                    <span className="font-medium">{ACTION_LABEL[a.action_type]}</span>
                    {a.account_id != null && (
                      <span className="text-text-tertiary">· #{a.account_id}</span>
                    )}
                  </div>
                  {a.reason && (
                    <p className="mt-0.5 truncate text-[12px] text-text-tertiary">
                      {a.reason}
                    </p>
                  )}
                </div>
                <span className="whitespace-nowrap text-[11px] text-text-tertiary">
                  {timeAgo(a.created_at)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">
            Пока пусто. Автопилот отчитывается сюда после каждого тика (раз в 10 минут).
          </p>
        )}
      </Section>

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить цель?"
        message={
          toDelete
            ? `«${GOAL_LABEL[toDelete.goal_type]}» будет удалена, автопилот перестанет её поддерживать.`
            : ""
        }
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls =
    status === "executed"
      ? "bg-success"
      : status === "failed"
      ? "bg-danger"
      : status === "skipped"
      ? "bg-warning"
      : "bg-accent";
  return <span className={`mt-1.5 inline-block h-2 w-2 rounded-full ${cls}`} />;
}

function GoalRow({
  goal,
  onToggle,
  onDelete,
}: {
  goal: Goal;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const key = GOAL_PARAM_KEY[goal.goal_type];
  const value = goal.params[key];
  const op = goal.goal_type === "keep_low_risk" ? "<" : "=";
  return (
    <div className="card flex items-center gap-3 px-4 py-3">
      <span
        className={`inline-block h-2 w-2 rounded-full ${
          goal.enabled ? "bg-success" : "bg-text-tertiary/40"
        }`}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] text-text-primary">
          {GOAL_LABEL[goal.goal_type]}{" "}
          <span className="text-text-tertiary">
            {op} {value}
          </span>
        </p>
        <p className="truncate text-[12px] text-text-tertiary">
          {goal.enabled ? "Активна" : "Приостановлена"}
        </p>
      </div>
      <button
        onClick={onToggle}
        aria-label={goal.enabled ? "Приостановить" : "Возобновить"}
        className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
      >
        {goal.enabled ? (
          <Power className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        ) : (
          <Play className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        )}
      </button>
      <button
        onClick={onDelete}
        aria-label="Удалить"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical"
      >
        <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </button>
    </div>
  );
}

/* Unused imports scrubbed */
void Check;
void X;
