import { Lock } from "lucide-react";
import { useNavigate } from "react-router-dom";

/* Пейволл-капсула модуля прайминга (prompt 7.7).
   Стилистика — как у commenting/shilling: --accent-капсула, без
   оранжевого CTA. Копирайт: «Прайминг — конверсия через системные Push». */

export function PaywallCapsule() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-8 max-w-md">
      <div className="card p-6 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-pill bg-surface-2">
          <Lock
            className="h-5 w-5 text-text-secondary"
            strokeWidth={2}
            aria-hidden
          />
        </div>
        <div className="mt-4 text-[18px] font-semibold text-text-primary">
          Модуль на тарифе Pro
        </div>
        <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
          Прайминг — конверсия через системные Push. Мягкие MTProto-события
          триггерят у цели родное уведомление, но не оставляют артефактов
          в чате. Профиль-аватар-Bio — точка конверсии.
        </p>
        <button
          type="button"
          onClick={() => navigate("/billing")}
          className="mt-5 inline-flex h-10 items-center justify-center rounded-pill bg-accent px-5 text-[14px] font-semibold text-accent-on active:opacity-80"
        >
          Перейти на Pro
        </button>
      </div>
    </div>
  );
}
