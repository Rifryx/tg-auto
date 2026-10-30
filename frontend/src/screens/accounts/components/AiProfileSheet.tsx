import { useState } from "react";
import { CapsuleButton } from "./ui";

/* Конфигуратор bulk-действия generate_and_apply_profile («Профиль ИИ»).
 *
 * Запрос: оформление должно идти с предварительным описанием желаемого от
 * пользователя — ИИ генерит ПО ПРОМПТУ. Промпт опционален: пусто → генерим из
 * персоны аккаунта (как раньше). С промптом персона не обязательна. */
export function AiProfileSheet({
  count,
  busy,
  onApply,
  onCancel,
}: {
  count: number;
  busy: boolean;
  onApply: (payload: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [applyBio, setApplyBio] = useState(true);
  const [applyUsername, setApplyUsername] = useState(true);

  const build = (): Record<string, unknown> => {
    const p: Record<string, unknown> = {
      apply_bio: applyBio,
      apply_username: applyUsername,
    };
    const trimmed = prompt.trim();
    if (trimmed) p.prompt = trimmed;
    return p;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center px-4 pb-8 lg:items-center lg:pb-0 bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[440px] rounded-card border border-strong bg-bg-elevated p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[18px] font-semibold text-text-primary">Профиль ИИ</h3>
        <p className="mt-1.5 text-[13px] text-text-secondary">
          Сгенерировать и применить оформление на {count} акк. Опишите желаемый
          образ — ИИ сгенерит по описанию. Пусто — возьмём портрет из персоны
          аккаунта.
        </p>

        <div className="mt-4">
          <label className="mb-1 block text-[13px] text-text-secondary">
            Описание оформления (промпт)
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            placeholder="напр. крипто-трейдер из Москвы, 25 лет, лаконичное bio без эмодзи, ник в стиле trader_xxx"
            className="w-full resize-none rounded-xl border border-hairline bg-surface-2 p-2.5 text-[14px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </div>

        <div className="mt-3 flex flex-col gap-2 rounded-card border border-hairline p-3">
          <label className="flex items-center justify-between">
            <span className="text-[14px] text-text-secondary">Применять BIO</span>
            <input
              type="checkbox"
              checked={applyBio}
              onChange={(e) => setApplyBio(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
          </label>
          <label className="flex items-center justify-between">
            <span className="text-[14px] text-text-secondary">Подбирать username</span>
            <input
              type="checkbox"
              checked={applyUsername}
              onChange={(e) => setApplyUsername(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent)]"
            />
          </label>
        </div>

        <div className="mt-4 flex flex-col gap-2">
          <CapsuleButton
            variant="accent"
            disabled={busy}
            onClick={() => onApply(build())}
          >
            {busy ? "Запускаем…" : "Сгенерировать и применить"}
          </CapsuleButton>
          <CapsuleButton variant="secondary" onClick={onCancel} disabled={busy}>
            Отмена
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
