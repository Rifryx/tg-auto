import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { billingApi, type CurtainPromo } from "../shared/billing";
import { useCurrentPlan } from "../shared/store";
import { hapticSelection } from "../shared/tg";

/* Одноразовая «шторка» акции.
   Показывается, пока на сервере есть активная акция и пользователь её не скрыл.
   Крестик пишет скрытие на сервер (per-user) → больше не всплывает (на всех
   устройствах). Новая акция = новый id ⇒ покажется снова. Pro-пользователям не
   показываем — им акция на подписку не нужна. */
export function PromoCurtain() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const plan = useCurrentPlan();

  const { data } = useQuery({
    queryKey: ["billing", "promo"],
    queryFn: () => billingApi.getPromo(),
    staleTime: 60_000,
  });

  const dismiss = useMutation({
    mutationFn: (id: number) => billingApi.dismissPromo(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing", "promo"] }),
  });

  const promo: CurtainPromo | null = data?.promo ?? null;
  if (!promo || plan.id === "pro") return null;

  const close = () => {
    hapticSelection();
    dismiss.mutate(promo.id);
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-[60] flex justify-center px-4 pb-[calc(env(safe-area-inset-bottom)+12px)]">
      <div
        className={`promo-curtain promo-curtain--${promo.badge_variant} relative w-full max-w-[440px] overflow-hidden rounded-[22px] p-4 pr-11`}
      >
        <button
          type="button"
          onClick={close}
          aria-label="Скрыть"
          className="absolute right-3 top-3 inline-flex h-7 w-7 items-center justify-center rounded-full bg-black/25 text-white/90 active:bg-black/40"
        >
          <X className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>

        <div className="flex items-start gap-3">
          <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-white/20 text-white">
            <Sparkles className="h-5 w-5" strokeWidth={2} aria-hidden />
          </span>
          <div className="min-w-0 text-white">
            <p className="text-[15px] font-bold leading-tight">{promo.title}</p>
            {promo.description && (
              <p className="mt-0.5 text-[13px] leading-snug opacity-90">
                {promo.description}
              </p>
            )}
            <button
              type="button"
              onClick={() => {
                hapticSelection();
                navigate("/billing");
              }}
              className="mt-2.5 rounded-pill bg-white px-4 py-1.5 text-[13px] font-semibold text-black active:opacity-90"
            >
              Оформить Pro
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
