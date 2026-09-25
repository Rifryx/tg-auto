import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { shillingApi } from "../api";
import type { Role, Step } from "../types";
import { RoleAvatar, roleColor } from "./RoleCard";

/* Живое превью диалога в стиле Telegram-обсуждения. Данные берём из тех же
   query-ключей, что и редактор (react-query дедуплицирует). */
export function ScenarioPreview({
  campaignId,
  scenarioId,
  activeStepId,
  onHover,
  onGenerate,
}: {
  campaignId: number;
  scenarioId: number;
  activeStepId: number | null;
  onHover: (stepId: number | null) => void;
  onGenerate?: () => void;
}) {
  const campaign = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });
  const roles = useQuery({
    queryKey: ["shilling", "scenario", scenarioId, "roles"],
    queryFn: () => shillingApi.roles(scenarioId),
  });
  const steps = useQuery({
    queryKey: ["shilling", "scenario", scenarioId, "steps"],
    queryFn: () => shillingApi.steps(scenarioId),
  });

  const roleList: Role[] = roles.data ?? [];
  const stepList: Step[] = steps.data ?? [];
  const roleIndexById = new Map(roleList.map((r, i) => [r.id, i]));
  const orderById = new Map(stepList.map((s, i) => [s.id, i + 1]));

  const replyMin = campaign.data?.reply_delay_min_sec ?? 5;
  const replyMax = campaign.data?.reply_delay_max_sec ?? 15;
  const avgReply = Math.round((replyMin + replyMax) / 2);
  const durationSec = stepList.reduce(
    (acc, s) => acc + (s.delay_before_sec ?? avgReply),
    0,
  );

  return (
    <div className="card overflow-hidden">
      {/* Шапка «канала» */}
      <div className="flex items-center gap-2 border-b border-hairline bg-surface-1 px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-[13px] text-text-secondary">
          #
        </span>
        <div className="min-w-0">
          <p className="truncate text-[14px] font-semibold text-text-primary">
            Превью обсуждения
          </p>
          <p className="text-[11px] text-text-tertiary">как увидят участники чата</p>
        </div>
      </div>

      {/* Лента сообщений */}
      <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto bg-bg-base px-3 py-4">
        {stepList.length === 0 ? (
          <p className="py-8 text-center text-[13px] text-text-tertiary">
            Реплики появятся здесь по мере наполнения сценария.
          </p>
        ) : (
          stepList.map((step) => {
            const roleIdx = roleIndexById.get(step.role_id) ?? 0;
            const role = roleList[roleIdx];
            const replyOrder =
              step.reply_to_step_id != null ? orderById.get(step.reply_to_step_id) : null;
            const replyText =
              step.reply_to_step_id != null
                ? stepList.find((s) => s.id === step.reply_to_step_id)?.text
                : null;
            return (
              <PreviewBubble
                key={step.id}
                step={step}
                role={role}
                roleIndex={roleIdx}
                replyOrder={replyOrder ?? null}
                replyText={replyText ?? null}
                active={activeStepId === step.id}
                onEnter={() => onHover(step.id)}
                onLeave={() => onHover(null)}
              />
            );
          })
        )}
      </div>

      {/* Футер: оценка длительности + генерация */}
      <div className="flex items-center justify-between gap-2 border-t border-hairline bg-surface-1 px-4 py-3">
        <span className="text-[12px] text-text-tertiary">
          💡 Диалог займёт ~{durationSec}с
        </span>
        {onGenerate && (
          <button
            onClick={onGenerate}
            className="inline-flex items-center gap-1.5 rounded-pill bg-accent px-3.5 py-1.5 text-[13px] font-medium text-accent-on active:opacity-80"
          >
            <Sparkles className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            Сгенерировать через ИИ
          </button>
        )}
      </div>
    </div>
  );
}

function PreviewBubble({
  step,
  role,
  roleIndex,
  replyOrder,
  replyText,
  active,
  onEnter,
  onLeave,
}: {
  step: Step;
  role?: Role;
  roleIndex: number;
  replyOrder: number | null;
  replyText: string | null;
  active: boolean;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const color = role ? roleColor(role, roleIndex) : "#888";
  const isReaction = step.step_type === "reaction";
  return (
    <div
      className="flex items-start gap-2"
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <RoleAvatar name={role?.name ?? "?"} color={color} size={28} />
      <div className="min-w-0 flex-1">
        <p className="mb-0.5 text-[11px] font-medium" style={{ color }}>
          {role?.name ?? "—"}
        </p>
        <div
          className={[
            "inline-block max-w-full rounded-2xl rounded-tl-md border px-3 py-2 transition-all",
            active
              ? "border-accent bg-surface-2 ring-1 ring-accent"
              : "border-hairline bg-surface-1",
          ].join(" ")}
        >
          {replyOrder != null && (
            <div className="mb-1 border-l-2 border-accent/60 pl-2">
              <p className="text-[10px] text-text-tertiary">Ответ на #{replyOrder}</p>
              {replyText && (
                <p className="truncate text-[11px] text-text-secondary">{replyText}</p>
              )}
            </div>
          )}
          {isReaction ? (
            <span className="text-[18px]">{step.reaction_emoji || "👍"}</span>
          ) : (
            <p className="whitespace-pre-wrap text-[13px] leading-snug text-text-primary">
              {step.text || <span className="text-text-tertiary">пустая реплика</span>}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
