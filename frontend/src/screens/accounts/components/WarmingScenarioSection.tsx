import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import {
  PRESET_WARMING_DEFAULTS,
  PROFILE_LABEL,
  WARMING_ACTION_LABEL,
} from "../../../shared/status";
import type { WarmingProfile, WarmingScenario } from "../../../shared/types";
import { Field, TextInput } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";

const ACTIONS = Object.keys(WARMING_ACTION_LABEL);

type Form = {
  intervalMin: string;
  intervalMax: string;
  actionsMin: string;
  actionsMax: string;
  weights: Record<string, number>;
  readyActions: string;
  readyDays: string;
};

function hasCustom(s: WarmingScenario | undefined): boolean {
  if (!s) return false;
  return (
    s.interval_hours_min != null ||
    s.actions_min != null ||
    (s.action_weights != null && Object.keys(s.action_weights).length > 0) ||
    s.ready_actions != null ||
    s.ready_days != null
  );
}

function seedForm(s: WarmingScenario | undefined, profile: WarmingProfile): Form {
  const preset = PRESET_WARMING_DEFAULTS[profile];
  const weights: Record<string, number> = {};
  for (const a of ACTIONS) weights[a] = s?.action_weights?.[a] ?? 1;
  return {
    intervalMin: String(s?.interval_hours_min ?? preset.interval[0]),
    intervalMax: String(s?.interval_hours_max ?? preset.interval[1]),
    actionsMin: String(s?.actions_min ?? preset.actions[0]),
    actionsMax: String(s?.actions_max ?? preset.actions[1]),
    weights,
    readyActions: s?.ready_actions != null ? String(s.ready_actions) : "",
    readyDays: s?.ready_days != null ? String(s.ready_days) : "",
  };
}

/* Конструктор сценариев прогрева (карточка аккаунта).
 *
 * Поверх пресета интенсивности позволяет задать свой темп: интервал между
 * действиями, размер стартовой пачки, микс действий (веса, 0 = выкл) и
 * критерий готовности. Хранится в accounts.meta; пустой сценарий = работает
 * пресет. */
export function WarmingScenarioSection({
  accountId,
  profile,
}: {
  accountId: number;
  profile: WarmingProfile;
}) {
  const qc = useQueryClient();
  const scenario = useQuery({
    queryKey: ["account", accountId, "warming-scenario"],
    queryFn: () => accountsApi.warmingScenario(accountId),
  });

  const custom = hasCustom(scenario.data);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>(seedForm(undefined, profile));
  const [saved, setSaved] = useState(false);

  // Как только пришли данные — синхронизируем форму (если не редактируем).
  useEffect(() => {
    if (!editing && scenario.data) setForm(seedForm(scenario.data, profile));
  }, [scenario.data, profile, editing]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["account", accountId, "warming-scenario"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const body = {
        interval_hours_min: Number(form.intervalMin),
        interval_hours_max: Number(form.intervalMax),
        actions_min: Number(form.actionsMin),
        actions_max: Number(form.actionsMax),
        action_weights: form.weights,
        ready_actions: form.readyActions ? Number(form.readyActions) : null,
        ready_days: form.readyDays ? Number(form.readyDays) : null,
      };
      return accountsApi.setWarmingScenario(accountId, body);
    },
    onSuccess: () => {
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      invalidate();
    },
  });

  const reset = useMutation({
    mutationFn: () => accountsApi.clearWarmingScenario(accountId),
    onSuccess: () => {
      setEditing(false);
      invalidate();
    },
  });

  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  // Свёрнутый вид: пресет активен, кнопка «настроить вручную».
  if (!editing && !custom) {
    return (
      <Section title="Сценарий прогрева">
        <div className="flex items-start gap-2 text-[13px] text-text-secondary">
          <SlidersHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
          <span>
            Используется пресет «{PROFILE_LABEL[profile]}». Можно задать свой темп
            и микс действий.
          </span>
        </div>
        <div className="mt-3">
          <CapsuleButton
            variant="secondary"
            onClick={() => {
              setForm(seedForm(scenario.data, profile));
              setEditing(true);
            }}
          >
            Настроить вручную
          </CapsuleButton>
        </div>
      </Section>
    );
  }

  const invalidInterval = Number(form.intervalMax) < Number(form.intervalMin);
  const invalidActions = Number(form.actionsMax) < Number(form.actionsMin);
  const anyWeight = Object.values(form.weights).some((w) => w > 0);
  const canSave =
    !invalidInterval && !invalidActions && anyWeight && !save.isPending;

  return (
    <Section title="Сценарий прогрева">
      {!editing && custom && (
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[13px] text-status-active">Активен кастомный сценарий</span>
          <button
            onClick={() => setEditing(true)}
            className="rounded-full border border-hairline bg-surface-2 px-3 py-1 text-[12px] text-text-secondary active:text-text-primary"
          >
            Изменить
          </button>
        </div>
      )}

      {editing && (
        <>
          <p className="mb-2 px-0.5 text-[13px] font-semibold text-text-primary">
            Интервал между действиями, ч
          </p>
          <div className="mb-4 flex gap-2">
            <Field label="от">
              <TextInput
                value={form.intervalMin}
                onChange={(e) => set({ intervalMin: e.target.value.replace(/[^\d.]/g, "") })}
                inputMode="decimal"
              />
            </Field>
            <Field label="до">
              <TextInput
                value={form.intervalMax}
                onChange={(e) => set({ intervalMax: e.target.value.replace(/[^\d.]/g, "") })}
                inputMode="decimal"
              />
            </Field>
          </div>
          {invalidInterval && (
            <p className="-mt-2 mb-3 text-[12px] text-status-critical">«до» должно быть ≥ «от».</p>
          )}

          <p className="mb-2 px-0.5 text-[13px] font-semibold text-text-primary">
            Действий в стартовой пачке
          </p>
          <div className="mb-4 flex gap-2">
            <Field label="от">
              <TextInput
                value={form.actionsMin}
                onChange={(e) => set({ actionsMin: e.target.value.replace(/\D/g, "") })}
                inputMode="numeric"
              />
            </Field>
            <Field label="до">
              <TextInput
                value={form.actionsMax}
                onChange={(e) => set({ actionsMax: e.target.value.replace(/\D/g, "") })}
                inputMode="numeric"
              />
            </Field>
          </div>
          {invalidActions && (
            <p className="-mt-2 mb-3 text-[12px] text-status-critical">«до» должно быть ≥ «от».</p>
          )}

          <p className="mb-2 px-0.5 text-[13px] font-semibold text-text-primary">
            Микс действий
          </p>
          <div className="mb-4 flex flex-col gap-2.5">
            {ACTIONS.map((a) => (
              <div key={a} className="flex items-center gap-3">
                <span className="w-[150px] shrink-0 text-[13px] text-text-secondary">
                  {WARMING_ACTION_LABEL[a]}
                </span>
                <input
                  type="range"
                  min={0}
                  max={3}
                  step={0.5}
                  value={form.weights[a]}
                  onChange={(e) =>
                    set({ weights: { ...form.weights, [a]: Number(e.target.value) } })
                  }
                  className="h-1 flex-1 accent-[var(--accent)]"
                />
                <span className="w-9 shrink-0 text-right text-[12px] text-text-tertiary">
                  {form.weights[a] === 0 ? "выкл" : `×${form.weights[a]}`}
                </span>
              </div>
            ))}
          </div>
          {!anyWeight && (
            <p className="-mt-2 mb-3 text-[12px] text-status-critical">
              Хотя бы одно действие должно быть включено.
            </p>
          )}

          <p className="mb-2 px-0.5 text-[13px] font-semibold text-text-primary">
            Готовность (warming → пул)
          </p>
          <div className="mb-4 flex gap-2">
            <Field label="действий">
              <TextInput
                value={form.readyActions}
                onChange={(e) => set({ readyActions: e.target.value.replace(/\D/g, "") })}
                inputMode="numeric"
                placeholder="по умолч. 50"
              />
            </Field>
            <Field label="или дней">
              <TextInput
                value={form.readyDays}
                onChange={(e) => set({ readyDays: e.target.value.replace(/\D/g, "") })}
                inputMode="numeric"
                placeholder="по умолч. 14"
              />
            </Field>
          </div>

          {save.isError && (
            <p className="mb-2 text-[12px] text-status-critical">
              Не удалось сохранить. Проверьте значения.
            </p>
          )}

          <div className="flex gap-2">
            <CapsuleButton
              variant="secondary"
              onClick={() => {
                setEditing(false);
                setForm(seedForm(scenario.data, profile));
              }}
            >
              Отмена
            </CapsuleButton>
            <CapsuleButton
              variant={canSave ? "accent" : "secondary"}
              disabled={!canSave}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Сохраняем…" : "Сохранить сценарий"}
            </CapsuleButton>
          </div>

          {custom && (
            <button
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
              className="mt-3 text-[13px] text-status-critical active:opacity-70"
            >
              {reset.isPending ? "Сбрасываем…" : "Сбросить к пресету"}
            </button>
          )}
        </>
      )}

      {saved && (
        <p className="mt-2 flex items-center gap-1.5 text-[12px] text-status-active">
          <Check className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
          Сценарий сохранён.
        </p>
      )}
    </Section>
  );
}
