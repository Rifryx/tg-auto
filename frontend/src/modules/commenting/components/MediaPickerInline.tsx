import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { mediaAssetsApi } from "../../../shared/media";
import { MediaAssetThumb } from "./MediaAssetThumb";
import { CapsuleButton } from "./ui";

/* Инлайн-пикер картинок для создания кампании: кампании ещё нет (id не
   присвоен), поэтому работаем напрямую с общей библиотекой медиа
   пользователя (/media-assets) — загрузка и выбор доступны сразу, а
   привязка к кампании (setMedia) происходит после её создания. Без этого
   тумблер «Картинка к комментарию» было некуда заполнить контентом. */
export function MediaPickerInline({
  selected,
  onChange,
}: {
  selected: number[];
  onChange: (ids: number[]) => void;
}) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["media-assets"], queryFn: mediaAssetsApi.list });
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => mediaAssetsApi.upload(file),
    onSuccess: (asset) => {
      onChange([...selected, asset.id]);
      setError(null);
      qc.invalidateQueries({ queryKey: ["media-assets"] });
    },
    onError: (e: Error) => setError(e.message || "Не удалось загрузить"),
  });

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  const items = list.data ?? [];

  return (
    <div className="mt-2 rounded-chip border border-hairline bg-surface-1 p-3">
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload.mutate(f);
          if (fileRef.current) fileRef.current.value = "";
        }}
      />
      {items.length === 0 && !list.isLoading ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-[12px] text-text-tertiary">
            Картинок пока нет — без хотя бы одной тумблер ничего не приложит, уйдёт
            обычный текст. Загрузите одну или несколько прямо сейчас.
          </p>
          <CapsuleButton
            variant="secondary"
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
            className="w-auto px-4"
          >
            <span className="inline-flex items-center gap-1.5">
              <ImagePlus className="h-4 w-4" strokeWidth={2} aria-hidden />
              {upload.isPending ? "Загружаем…" : "Загрузить картинку"}
            </span>
          </CapsuleButton>
        </div>
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[12px] text-text-tertiary">
              Отметьте, какие можно прикладывать · выбрано {selected.length}
            </p>
            <button
              type="button"
              disabled={upload.isPending}
              onClick={() => fileRef.current?.click()}
              className="inline-flex shrink-0 items-center gap-1 text-[12px] text-text-secondary active:text-text-primary disabled:opacity-50"
            >
              <ImagePlus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              {upload.isPending ? "Загружаем…" : "Загрузить"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {items.map((a) => {
              const active = selected.includes(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggle(a.id)}
                  className={`relative overflow-hidden rounded-chip border transition-colors ${
                    active ? "border-strong" : "border-hairline active:border-strong"
                  }`}
                >
                  <MediaAssetThumb id={a.id} size={64} />
                  {active && (
                    <span className="pointer-events-none absolute inset-0 flex items-end justify-end bg-accent/20 p-1">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-accent-on">
                        ✓
                      </span>
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm("Удалить картинку из хранилища?")) {
                        mediaAssetsApi.remove(a.id).then(() => {
                          onChange(selected.filter((id) => id !== a.id));
                          qc.invalidateQueries({ queryKey: ["media-assets"] });
                        });
                      }
                    }}
                    aria-label="Удалить из хранилища"
                    className="absolute left-0.5 top-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-bg-elevated/80 text-text-secondary active:text-status-critical"
                  >
                    <Trash2 className="h-3 w-3" strokeWidth={2} aria-hidden />
                  </button>
                </button>
              );
            })}
          </div>
        </>
      )}
      {error && <p className="mt-2 text-[12px] text-status-critical">{error}</p>}
    </div>
  );
}
