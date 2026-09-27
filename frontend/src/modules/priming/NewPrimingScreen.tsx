import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";

/* Мастер новой кампании прайминга (docs/priming-ui.md §5) — приезжает на
   промпте 2.8. Пока — заглушка со ссылкой обратно. */
export function NewPrimingScreen() {
  const navigate = useNavigate();
  return (
    <div className="min-h-full pb-24">
      <ScreenHeader
        title="Новая кампания"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/priming")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К списку
          </button>
        }
      />
      <div className="card p-5">
        <p className="text-[14px] text-text-secondary">
          Мастер новой кампании ещё в разработке (промпт 2.8). Полная спека
          и порядок секций — в docs/priming-ui.md §5.
        </p>
      </div>
    </div>
  );
}
