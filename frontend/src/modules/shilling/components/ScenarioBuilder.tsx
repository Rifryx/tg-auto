import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Plus, Smile } from "lucide-react";
import { useState } from "react";
import { shillingApi } from "../api";
import type { Role, Step } from "../types";
import { GenerateScenarioSheet } from "./GenerateScenarioSheet";
import { RoleCard, roleColor } from "./RoleCard";
import { ScenarioPreview } from "./ScenarioPreview";
import { StepBubble } from "./StepBubble";
import type { ReplyOption, ReplyTarget } from "./StepBubble";

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
  const [genOpen, setGenOpen] = useState(false);

  const campaign = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });

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
            onGenerate={() => setGenOpen(true)}
          />
        </div>
      </div>

      <GenerateScenarioSheet
        open={genOpen}
        campaignId={campaignId}
        scenarioId={scenarioId}
        defaultBrand={campaign.data?.brand_name ?? null}
        onClose={() => setGenOpen(false)}
        onApplied={() => setActiveStepId(null)}
      />
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
    meta: { silent: true }, // ошибку показываем inline (роль с репликами)
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
  const changeStepRole = useMutation({
    mutationFn: (p: { id: number; roleId: number }) =>
      shillingApi.updateStep(scenarioId, p.id, { role_id: p.roleId }),
    onSuccess: invalidateSteps,
  });
  const deleteStep = useMutation({
    mutationFn: (id: number) => shillingApi.removeStep(scenarioId, id),
    onSuccess: invalidateSteps,
  });
  // «Ответить на сообщение» / «просто отправка»: проставляем или снимаем
  // reply_to_step_id. В рантайме это решает, отвечает ли бот на конкретное
  // сообщение (цитата) или шлёт реплику без ответа.
  const setReply = useMutation({
    mutationFn: (p: { id: number; targetId: number | null }) =>
      shillingApi.updateStep(scenarioId, p.id, { reply_to_step_id: p.targetId }),
    onSuccess: invalidateSteps,
  });
  // Перестановка шагов перетаскиванием. localOrder держим, пока сервер не
  // подтвердит — чтобы список не прыгал; при ошибке откатываемся к серверному.
  const [localOrder, setLocalOrder] = useState<number[] | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const reorder = useMutation({
    mutationFn: (ids: number[]) => shillingApi.reorderSteps(scenarioId, ids),
    onSuccess: () => {
      setLocalOrder(null);
      invalidateSteps();
    },
    onError: () => setLocalOrder(null),
  });

  const roleList: Role[] = roles.data ?? [];
  const serverSteps: Step[] = steps.data ?? [];
  // Во время перетаскивания показываем локальный порядок, иначе серверный.
  const stepById = new Map(serverSteps.map((s) => [s.id, s]));
  const stepList: Step[] =
    localOrder != null
      ? localOrder.map((id) => stepById.get(id)).filter((s): s is Step => s != null)
      : serverSteps;
  const firstRoleId = roleList[0]?.id;

  // Новый шаг добавляем от СЛЕДУЮЩЕЙ роли (чередование) — диалог естественно
  // идёт «туда-сюда», а не всегда от одной персоны. Роль потом можно сменить в
  // самом шаге. Если роль одна — она же и используется.
  const nextRoleId = (): number | undefined => {
    if (roleList.length === 0) return undefined;
    const last = stepList[stepList.length - 1];
    if (!last) return roleList[0].id;
    const idx = roleList.findIndex((r) => r.id === last.role_id);
    if (idx < 0) return roleList[0].id;
    return roleList[(idx + 1) % roleList.length].id;
  };

  // Позиция шага по id (1-based) в текущем отображаемом порядке — для цитат.
  const orderById = new Map(stepList.map((s, i) => [s.id, i + 1]));
  const roleMeta = (roleId: number): { roleName: string; color: string } => {
    const idx = roleList.findIndex((r) => r.id === roleId);
    const r = roleList[idx];
    return { roleName: r?.name || "—", color: r ? roleColor(r, idx) : "#888" };
  };
  const stepPreview = (s: Step): string =>
    s.step_type === "reaction" ? s.reaction_emoji || "👍" : s.text?.trim() || "пустая реплика";

  // Drag: при входе в чужой ряд перемещаем перетаскиваемый шаг на его место.
  const beginDrag = (id: number) => {
    setDragId(id);
    if (localOrder == null) setLocalOrder(stepList.map((s) => s.id));
  };
  const hoverDrag = (overId: number) => {
    if (dragId == null || dragId === overId) return;
    setLocalOrder((prev) => {
      const base = prev ?? stepList.map((s) => s.id);
      const from = base.indexOf(dragId);
      const to = base.indexOf(overId);
      if (from < 0 || to < 0 || from === to) return base;
      const next = base.slice();
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });
  };
  const endDrag = () => {
    setDragId(null);
    if (localOrder == null) return;
    const serverIds = serverSteps.map((s) => s.id).join(",");
    if (localOrder.join(",") !== serverIds) {
      reorder.mutate(localOrder);
    } else {
      setLocalOrder(null); // порядок не изменился — снимаем локальный
    }
  };

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
              // Цитата ответа: цель должна быть ВИДНА (есть в списке) — иначе
              // (например, цель удалили) показывать нечего.
              const target =
                step.reply_to_step_id != null ? stepById.get(step.reply_to_step_id) : undefined;
              const replyTarget: ReplyTarget | null =
                target != null
                  ? {
                      order: orderById.get(target.id) ?? 0,
                      preview: stepPreview(target),
                      ...roleMeta(target.role_id),
                    }
                  : null;
              // Ответить можно только на более ранние шаги — то, что в рантайме
              // уже будет отправлено к моменту этой реплики.
              const replyOptions: ReplyOption[] = stepList.slice(0, i).map((s, j) => ({
                stepId: s.id,
                order: j + 1,
                preview: stepPreview(s),
                ...roleMeta(s.role_id),
              }));
              return (
                <StepBubble
                  key={step.id}
                  step={step}
                  index={i + 1}
                  roles={roleList}
                  roleIndex={roleIdx}
                  replyTarget={replyTarget}
                  replyOptions={replyOptions}
                  onSetReply={(targetId) => setReply.mutate({ id: step.id, targetId })}
                  active={activeStepId === step.id}
                  onHoverStart={() => onHover(step.id)}
                  onHoverEnd={() => onHover(null)}
                  onEditText={(text) => editStep.mutate({ id: step.id, text })}
                  onChangeRole={(roleId) => changeStepRole.mutate({ id: step.id, roleId })}
                  onDelete={() => deleteStep.mutate(step.id)}
                  dragging={dragId === step.id}
                  dropTarget={dragId != null && dragId !== step.id}
                  onDragStartRow={() => beginDrag(step.id)}
                  onDragEnterRow={() => hoverDrag(step.id)}
                  onDragEndRow={endDrag}
                />
              );
            })}
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={() => {
              const rid = nextRoleId();
              if (rid) addStep.mutate({ roleId: rid, type: "message" });
            }}
            disabled={!firstRoleId || addStep.isPending}
            className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3.5 py-2 text-[13px] text-text-secondary active:text-text-primary disabled:opacity-40"
          >
            <MessageSquarePlus className="h-4 w-4" strokeWidth={2} aria-hidden />
            Реплика
          </button>
          <button
            onClick={() => {
              const rid = nextRoleId();
              if (rid) addStep.mutate({ roleId: rid, type: "reaction" });
            }}
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
