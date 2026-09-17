import { Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { hapticSelection } from "./tg";
import { LIMIT_LABEL, useLimit } from "./limits";
import { UNLIMITED, type FeatureKey } from "./plans";

/* Инлайн-баннер над «Создать»: сколько осталось / упёрлись в лимит.
   На Pro при безлимите — не рендерится (тихо, без «Осталось ∞»). */
export function LimitBanner({ feature }: { feature: FeatureKey }) {
  const status = useLimit(feature);
  const navigate = useNavigate();
  if (!status) return null;
  if (status.limit === UNLIMITED) return null;

  const label = LIMIT_LABEL[feature] ?? "";
  const atLimit = status.atLimit;

  return (
    <button
      type="button"
      onClick={() => {
        hapticSelection();
        navigate("/billing");
      }}
      className={[
        "mb-3 flex w-full items-center gap-3 rounded-card border px-4 py-3 text-left transition-colors",
        atLimit
          ? "border-strong bg-surface-2 text-text-primary"
          : "border-hairline bg-surface-1 text-text-secondary active:bg-surface-2",
      ].join(" ")}
    >
      <span
        aria-hidden
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-pill"
        style={{
          background:
            "linear-gradient(135deg, #b291ff 0%, #7c5cff 100%)",
          color: "#1a0f45",
        }}
      >
        <Sparkles className="h-4 w-4" strokeWidth={2} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        {atLimit ? (
          <>
            <span className="text-[13.5px] font-semibold text-text-primary">
              Лимит {label} исчерпан на Free
            </span>
            <span className="text-[12px] text-text-tertiary">
              Использовано {status.used}/{status.limit}. Перейти на Pro →
            </span>
          </>
        ) : (
          <>
            <span className="text-[13.5px] text-text-primary">
              {status.used}/{status.limit} {label} — осталось {status.remaining}
            </span>
            <span className="text-[12px] text-text-tertiary">
              Снять ограничение — тариф Pro
            </span>
          </>
        )}
      </div>
    </button>
  );
}
