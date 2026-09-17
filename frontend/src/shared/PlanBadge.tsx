import { Sparkles } from "lucide-react";
import { useCurrentPlan } from "./store";

/* Маленькая пилюля с текущим планом.
   Free — тихая, hairline+text-tertiary. Pro — индиго-градиент со звёздочкой. */
export function PlanBadge({ size = "sm" }: { size?: "sm" | "md" }) {
  const plan = useCurrentPlan();
  const isPro = plan.id === "pro";
  const sizes =
    size === "md"
      ? "h-8 px-3 text-[13px]"
      : "h-7 px-2.5 text-[12px]";

  if (isPro) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-pill font-semibold text-white ${sizes}`}
        style={{
          background:
            "linear-gradient(135deg, #7c5cff 0%, #4b2fbf 55%, #2a1a80 100%)",
          boxShadow:
            "0 0 0 1px rgba(139,92,246,0.55) inset, 0 6px 18px -8px rgba(124,92,255,0.65)",
        }}
      >
        <Sparkles className={size === "md" ? "h-4 w-4" : "h-3.5 w-3.5"} strokeWidth={2} aria-hidden />
        Pro
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center rounded-pill border border-hairline bg-surface-1 font-medium text-text-secondary ${sizes}`}
    >
      Free
    </span>
  );
}
