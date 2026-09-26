import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import { shillingApi } from "../api";
import type { GeneratedScenario } from "../types";
import { NumberStepper, TextArea, TextInput, Toggle } from "../../commenting/components/ui";
import { RoleAvatar } from "./RoleCard";

/* Модалка/боттом-шит ИИ-генерации сценария. Генерирует черновик, показывает
   превью и по «Применить» пересобирает сценарий кампании (роли + шаги). */
export function GenerateScenarioSheet({
  open,
  campaignId,
  scenarioId,
  defaultBrand,
  onClose,
  onApplied,
}: {
  open: boolean;
  campaignId: number;
  scenarioId: number;
  defaultBrand: string | null;
  onClose: () => void;
  onApplied: () => void;
}) {
  const qc = useQueryClient();
  const [topic, setTopic] = useState("");
  const [brand, setBrand] = useState(defaultBrand ?? "");
  const [persons, setPersons] = useState("2");
  const [aiSteps, setAiSteps] = useState(true);
  const [stepsCount, setStepsCount] = useState("4");
  const [aiRoles, setAiRoles] = useState(true);
  const [draft, setDraft] = useState<GeneratedScenario | null>(null);

  const existingRoles = useQuery({
    queryKey: ["shilling", "scenario", scenarioId, "roles"],
    queryFn: () => shillingApi.roles(scenarioId),
    enabled: open,
  });

  const generate = useMutation({
    mutationFn: () =>
      shillingApi.generateScenario(campaignId, {
        topic: topic.trim(),
        brand_name: brand.trim() || null,
        persons_count: Number(persons) || 2,
        steps_count: aiSteps ? null : Number(stepsCount) || undefined,
        roles:
          !aiRoles && existingRoles.data && existingRoles.data.length
            ? existingRoles.data.map((r) => ({
                name: r.name,
                character: r.character ?? "",
              }))
            : null,
      }),
    onSuccess: (res) => setDraft(res),
    meta: { silent: true }, // inline-сообщение в форме
  });

  const apply = useMutation({
    mutationFn: async () => {
      if (!draft) return;
      // Пересобираем сценарий: PUT создаёт свежий (старые роли/шаги — каскадом).
      const scenario = await shillingApi.putScenario(campaignId, {
        persons_count: draft.roles.length || 2,
        ai_generated: true,
      });
      // Роли: name -> id.
      const roleIdByName = new Map<string, number>();
      for (let i = 0; i < draft.roles.length; i++) {
        const r = draft.roles[i];
        const created = await shillingApi.addRole(scenario.id, {
          name: r.name,
          character: r.character || null,
          sort_order: i,
        });
        roleIdByName.set(r.name, created.id);
      }
      // Шаги по порядку → запоминаем созданные id для reply-связок.
      const createdStepIds: number[] = [];
      for (const step of draft.steps) {
        const roleId = roleIdByName.get(step.role);
        if (roleId == null) continue;
        const created = await shillingApi.addStep(scenario.id, {
          role_id: roleId,
          step_type: "message",
          text: step.text,
        });
        createdStepIds.push(created.id);
      }
      // Второй проход: проставляем reply_to_step_id (1-based индекс в draft).
      for (let i = 0; i < draft.steps.length; i++) {
        const rt = draft.steps[i].reply_to_step;
        if (rt != null && rt >= 1 && rt <= createdStepIds.length && createdStepIds[i] != null) {
          await shillingApi.updateStep(scenario.id, createdStepIds[i], {
            reply_to_step_id: createdStepIds[rt - 1],
          });
        }
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "scenario"] });
      onApplied();
      onClose();
    },
    meta: { silent: true }, // inline-сообщение в превью
  });

  if (!open) return null;

  const canGenerate = topic.trim().length > 0 && !generate.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center">
      <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-card bg-bg-elevated p-5 sm:max-w-lg sm:rounded-card">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-text-primary">Сгенерировать сценарий</h2>
          <button onClick={onClose} aria-label="Закрыть" className="text-text-tertiary active:text-text-primary">
            <X className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        {!draft ? (
          <div className="flex flex-col gap-4">
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">
                Тема обсуждения
              </span>
              <TextArea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="Напр.: где найти хороший салон красоты в центре"
                rows={3}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">Бренд</span>
              <TextInput
                value={brand}
                onChange={(e) => setBrand(e.target.value)}
                placeholder="Напр.: Beauty Zone"
              />
            </label>
            <div>
              <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Количество персон</p>
              <NumberStepper value={persons} onChange={setPersons} min={2} max={10} />
            </div>
            <ToggleRow
              label="Количество реплик решает ИИ"
              checked={aiSteps}
              onChange={setAiSteps}
            />
            {!aiSteps && (
              <div>
                <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Сколько реплик</p>
                <NumberStepper value={stepsCount} onChange={setStepsCount} min={2} max={30} />
              </div>
            )}
            <ToggleRow
              label="Роли придумывает ИИ"
              hint={
                !aiRoles && (existingRoles.data?.length ?? 0) === 0
                  ? "Нет существующих ролей — ИИ придумает сам"
                  : undefined
              }
              checked={aiRoles}
              onChange={setAiRoles}
            />

            {generate.isError && (
              <p className="text-[13px] text-status-critical">
                Не удалось сгенерировать. Попробуйте изменить тему и повторить.
              </p>
            )}

            <button
              onClick={() => generate.mutate()}
              disabled={!canGenerate}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-pill bg-accent text-[15px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
            >
              <Sparkles className="h-4 w-4" strokeWidth={2.2} aria-hidden />
              {generate.isPending ? "ИИ пишет диалог…" : "Сгенерировать"}
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-[13px] text-text-tertiary">
              Черновик: {draft.roles.length} ролей, {draft.steps.length} реплик.
            </p>
            <div className="flex max-h-[45vh] flex-col gap-2 overflow-y-auto rounded-card bg-bg-base p-3">
              {draft.steps.map((s, i) => {
                const roleIdx = draft.roles.findIndex((r) => r.name === s.role);
                return (
                  <div key={i} className="flex items-start gap-2">
                    <RoleAvatar name={s.role} color={roleColorForIndex(roleIdx)} size={24} />
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium text-text-secondary">{s.role}</p>
                      <p className="text-[13px] text-text-primary">{s.text}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            {apply.isError && (
              <p className="text-[13px] text-status-critical">
                Не удалось применить сценарий. Попробуйте ещё раз.
              </p>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => setDraft(null)}
                className="h-11 flex-1 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80"
              >
                Ещё раз
              </button>
              <button
                onClick={() => apply.mutate()}
                disabled={apply.isPending}
                className="h-11 flex-1 rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
              >
                {apply.isPending ? "Применяем…" : "Применить"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const PALETTE = ["#f87171", "#fbbf24", "#34d399", "#60a5fa", "#a78bfa", "#f472b6", "#22d3ee", "#a3e635"];
function roleColorForIndex(i: number): string {
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-[14px] text-text-primary">{label}</p>
        {hint && <p className="mt-0.5 text-[12px] text-text-tertiary">{hint}</p>}
      </div>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  );
}
