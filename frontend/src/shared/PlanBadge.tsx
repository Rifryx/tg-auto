import { Sparkles } from "lucide-react";
import { useCurrentPlan, useHasActivePromo } from "./store";

export function PlanBadge({ size = "sm" }: { size?: "sm" | "md" }) {
  const plan = useCurrentPlan();
  const isPro = plan.id === "pro";
  const promo = useHasActivePromo();
  const sizes =
    size === "md" ? "h-8 px-3 text-[13px]" : "h-7 px-2.5 text-[12px]";
  const icon = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";

  if (isPro) {
    // Во время акции PRO-бейдж получает характерный «промо» вид (градиент +
    // свечение), чтобы подписка визуально выделялась.
    if (promo) {
      return (
        <span
          className={`promo-badge inline-flex items-center gap-1.5 rounded-pill font-semibold ${sizes}`}
        >
          <Sparkles className={icon} strokeWidth={2} aria-hidden />
          Pro
        </span>
      );
    }
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-pill border border-strong bg-surface-2 font-semibold text-text-primary ${sizes}`}
      >
        <Sparkles className={icon} strokeWidth={2} aria-hidden />
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
