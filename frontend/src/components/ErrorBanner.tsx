import { AlertTriangle, X } from "lucide-react";

/* Единый блок ошибки под стиль приложения: иконка слева (выровнена по первой
   строке), переносимый текст, опциональная кнопка «скрыть». Используется везде,
   где раньше падал сырой текст/JSON ошибки без оформления. */
export function ErrorBanner({
  message,
  onDismiss,
  className = "",
}: {
  message: string;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div
      className={`flex items-start gap-2.5 rounded-chip border border-status-critical/40 bg-status-critical/10 px-4 py-3 ${className}`}
      role="alert"
    >
      <AlertTriangle
        className="mt-0.5 h-4 w-4 shrink-0 text-status-critical"
        strokeWidth={2}
        aria-hidden
      />
      <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-status-critical [overflow-wrap:anywhere]">
        {message}
      </p>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Скрыть ошибку"
          className="-mr-1 -mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-status-critical/70 hover:text-status-critical"
        >
          <X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </button>
      )}
    </div>
  );
}
