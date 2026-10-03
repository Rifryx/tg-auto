/* Тонкий прогресс-бар (4 px), заполнение `--text-primary`, фон `--surface-2`.
   Не использует градиент — по правилам UI-DESIGN-BRIEF §8. */
export function ProgressLine({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div className="h-1 w-full overflow-hidden rounded-pill bg-surface-2">
      <div
        className="h-full bg-text-primary transition-all"
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}
