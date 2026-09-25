import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Plus, Smile } from "lucide-react";
import { useState } from "react";
import { shillingApi } from "../api";
import type { Role, Step } from "../types";
import { RoleCard } from "./RoleCard";
import { ScenarioPreview } from "./ScenarioPreview";
import { StepBubble } from "./StepBubble";

/* Конструктор сценария: слева редактор (роли + шаги), справа — превью (6.2).
   На узких экранах превью скрыто (появится pinnable-полосой в 6.2). */
export function ScenarioBuilder({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();

  const scenario = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "scenario"],
    queryFn: () => shillingApi.scenario(campaignId),
    retry: false, // 404 = сценария ещё нет
  });

  const createScenario = useMutation({
    mutationFn: () => shillingApi.putScenario(campaignId, { persons_count: 2 }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "scenario"] }),
  });

  if (scenario.isLoading) {
    return <div className="card h-40 animate-pulse bg-surface-2" />;
  }
  if (scenario.isError || !scenario.data) {
    return (
      <div className="card p-6 text-center">
        <p className="text-[15px] font-medium text-text-secondary">Сценарий не создан</p>
        <p className="mx-auto mt-1 mb-4 max-w-[280px] text-[13px] text-text-tertiary">
          Создайте сценарий, затем добавьте роли и реплики диалога.
        </p>
        <button
          onClick={() => createScenario.mutate()}
          disabled={createScenario.isPending}
          className="inline-flex h-10 items-center gap-1.5 rounded-pill bg-accent px-5 text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          Создать сценарий
        </button>
      </div>
    );
  }

  return <BuilderBody scenarioId={scenario.data.id} campaignId={campaignId} />;
}

function BuilderBody({
  scenarioId,
  campaignId,
}: {
  scenarioId: number;
  campaignId: number;
}) {
  // Общий hover-стейт для двусторонней подсветки редактор↔превью.
  const [activeStepId, setActiveStepId] = useState<number | null>(null);

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="lg:col-span-3">
        <ScenarioEditor
          scenarioId={scenarioId}
          activeStepId={activeStepId}
          onHover={setActiveStepId}
        />
      </div>
      <div className="lg:col-span-2">
        <div className="lg:sticky lg:top-4">
          <ScenarioPreview
            campaignId={campaignId}
            scenarioId={scenarioId}
            activeStepId={activeStepId}
            onHover={setActiveStepId}
          />
        </div>
      </div>
    </div>
  );
}

function ScenarioEditor({
  scenarioId,
  activeStepId,
  onHover,
}: {
  scenarioId: number;
  activeStepId: number | null;
  onHover: (stepId: number | null) => void;
}) {
  const qc = useQueryClient();
  const rolesKey = ["shilling", "scenario", scenarioId, "roles"];
  const stepsKey = ["shilling", "scenario", scenarioId, "steps"];

  const roles = useQuery({ queryKey: rolesKey, queryFn: () => shillingApi.roles(scenarioId) });
  const steps = useQuery({ queryKey: stepsKey, queryFn: () => shillingApi.steps(scenarioId) });

  const invalidateRoles = () => qc.invalidateQueries({ queryKey: rolesKey });
  const invalidateSteps = () => qc.invalidateQueries({ queryKey: stepsKey });

  const addRole = useMutation({
    mutationFn: () =>
      shillingApi.addRole(scenarioId, {
        name: `Роль ${(roles.data?.length ?? 0) + 1}`,
        sort_order: roles.data?.length ?? 0,
      }),
    onSuccess: invalidateRoles,
  });
  const renameRole = useMutation({
    mutationFn: (p: { id: number; name: string }) =>
      shillingApi.updateRole(scenarioId, p.id, { name: p.name }),
    onSuccess: invalidateRoles,
  });
  const characterRole = useMutation({
    mutationFn: (p: { id: number; character: string }) =>
      shillingApi.updateRole(scenarioId, p.id, { character: p.character }),
    onSuccess: invalidateRoles,
  });
  const deleteRole = useMutation({
    mutationFn: (id: number) => shillingApi.removeRole(scenarioId, id),
    onSuccess: invalidateRoles,
  });

  const addStep = useMutation({
    mutationFn: (p: { roleId: number; type: "message" | "reaction" }) =>
      shillingApi.addStep(scenarioId, {
        role_id: p.roleId,
        step_type: p.type,
        text: p.type === "message" ? "Новая реплика" : null,
        reaction_emoji: p.type === "reaction" ? "👍" : null,
      }),
    onSuccess: invalidateSteps,
  });
  const editStep = useMutation({
    mutationFn: (p: { id: number; text: string }) =>
      shillingApi.updateStep(scenarioId, p.id, { text: p.text }),
    onSuccess: invalidateSteps,
  });
  const deleteStep = useMutation({
    mutationFn: (id: number) => shillingApi.removeStep(scenarioId, id),
    onSuccess: invalidateSteps,
  });

  const roleList: Role[] = roles.data ?? [];
  const stepList: Step[] = steps.data ?? [];
  const firstRoleId = roleList[0]?.id;

  // Порядковый номер шага по id — для чипа «ответ на #N».
  const orderById = new Map(stepList.map((s, i) => [s.id, i + 1]));

  return (
    <div className="flex flex-col gap-5">
      {/* Роли */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
            Роли · {roleList.length}
          </h3>
          <button
            onClick={() => addRole.mutate()}
            disabled={addRole.isPending}
            className="inline-flex items-center gap-1 text-[13px] text-accent active:opacity-80"
          >
            <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
            Добавить роль
          </button>
        </div>
        {roleList.length === 0 ? (
          <p className="text-[13px] text-text-tertiary">
            Пока нет ролей. Добавьте «Инициатора» и «Ответчика».
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {roleList.map((role, i) => (
              <RoleCard
                key={role.id}
                role={role}
                index={i}
                onRename={(name) => renameRole.mutate({ id: role.id, name })}
                onCharacter={(character) => characterRole.mutate({ id: role.id, character })}
                onDelete={() => deleteRole.mutate(role.id)}
              />
            ))}
          </div>
        )}
        {deleteRole.isError && (
          <p className="mt-1 text-[12px] text-status-critical">
            Нельзя удалить роль, пока у неё есть реплики — сначала удалите их.
          </p>
        )}
      </section>

      {/* Шаги диалога */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
            Шаги диалога · {stepList.length}
          </h3>
        </div>
        {stepList.length === 0 ? (
          <p className="mb-3 text-[13px] text-text-tertiary">
            Добавьте реплики — по одной на шаг.
          </p>
        ) : (
          <div className="mb-3 flex flex-col gap-3">
            {stepList.map((step, i) => {
              const roleIdx = roleList.findIndex((r) => r.id === step.role_id);
              const replyOrder =
                step.reply_to_step_id != null
                  ? orderById.get(step.reply_to_step_id) ?? null
                  : null;
              return (
                <StepBubble
                  key={step.id}
                  step={step}
                  index={i + 1}
                  roles={roleList}
                  roleIndex={roleIdx}
                  replyTargetOrder={replyOrder}
                  active={activeStepId === step.id}
                  onHoverStart={() => onHover(step.id)}
                  onHoverEnd={() => onHover(null)}
                  onEditText={(text) => editStep.mutate({ id: step.id, text })}
                  onDelete={() => deleteStep.mutate(step.id)}
                />
              );
            })}
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={() => firstRoleId && addStep.mutate({ roleId: firstRoleId, type: "message" })}
            disabled={!firstRoleId || addStep.isPending}
            className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3.5 py-2 text-[13px] text-text-secondary active:text-text-primary disabled:opacity-40"
          >
            <MessageSquarePlus className="h-4 w-4" strokeWidth={2} aria-hidden />
            Реплика
          </button>
          <button
            onClick={() => firstRoleId && addStep.mutate({ roleId: firstRoleId, type: "reaction" })}
            disabled={!firstRoleId || addStep.isPending}
            className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3.5 py-2 text-[13px] text-text-secondary active:text-text-primary disabled:opacity-40"
          >
            <Smile className="h-4 w-4" strokeWidth={2} aria-hidden />
            Реакция
          </button>
        </div>
        {!firstRoleId && (
          <p className="mt-1 text-[12px] text-text-tertiary">
            Сначала добавьте хотя бы одну роль.
          </p>
        )}
      </section>
    </div>
  );
}
