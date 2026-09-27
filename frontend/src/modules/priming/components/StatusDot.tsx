import type { PrimingCampaignStatus } from "../types";

const DOT: Record<PrimingCampaignStatus, { className: string; pulse: boolean }> = {
  draft: { className: "bg-status-neutral", pulse: false },
  queued: { className: "bg-status-warning", pulse: false },
  running: { className: "bg-status-active", pulse: true },
  paused: { className: "bg-status-warning", pulse: false },
  stopped: { className: "bg-status-neutral", pulse: false },
  finished: { className: "bg-status-active", pulse: false },
  failed: { className: "bg-status-critical", pulse: false },
};

/* 8px точка-индикатор статуса кампании (UI бриф §7). */
export function StatusDot({ status }: { status: PrimingCampaignStatus }) {
  const meta = DOT[status];
  return (
    <span
      aria-hidden
      className={[
        "h-2 w-2 shrink-0 rounded-full",
        meta.className,
        meta.pulse ? "animate-pulse" : "",
      ].join(" ")}
    />
  );
}
