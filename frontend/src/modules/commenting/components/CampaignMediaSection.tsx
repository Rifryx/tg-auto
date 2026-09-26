import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { mediaAssetsApi } from "../../../shared/media";
import { commentingApi } from "../api";
import { MediaAssetThumb } from "./MediaAssetThumb";
import { CapsuleButton, Section } from "./ui";

/* Секция «Медиа кампании» (E4.1 attach_image UI).
 *
 * Работает с уже загруженными ассетами: приклеиваем их к кампании и
 * открепляем обратно. Загрузка новых файлов — через кнопку внутри
 * шторки выбора: файл уходит в /media-assets и сразу отмечается для
 * привязки. Сохранение — одной транзакцией PUT /campaigns/{id}/media. */
export function CampaignMediaSection({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const linked = useQuery({
    queryKey: ["campaign", campaignId, "media"],
    queryFn: () => commentingApi.media(campaignId),
  });
  const [pickerOpen, setPickerOpen] = useState(false);
  const remove = useMutation({
    mutationFn: (assetId: number) => {
      const current = linked.data?.media_asset_ids ?? [];
      return commentingApi.setMedia(
        campaignId,
        current.filter((id) => id !== assetId),
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaign", campaignId, "media"] }),
  });

  const attachedIds = linked.data?.media_asset_ids ?? [];

  return (
    <Section
      title={`Медиа кампании (${attachedIds.length})`}
      action={
        <button
          onClick={() => setPickerOpen(true)}
          className="inline-flex items-center gap-1 text-[13px] text-text-secondary active:text-text-primary"
        >
          <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
          Добавить
        </button>
      }
    >
      <div className="card p-4">
        {linked.isLoading ? (
          <p className="text-[13px] text-text-tertiary">Загрузка…</p>
        ) : attachedIds.length === 0 ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-[13px] text-text-tertiary">
              Картинок пока нет. Пока их нет, тумблер «Картинка к комментарию» ничего не
              приложит — обычный текст.
            </p>
            <CapsuleButton
              variant="secondary"
              onClick={() => setPickerOpen(true)}
              className="w-auto px-4"
            >
              <span className="inline-flex items-center gap-1.5">
                <ImagePlus className="h-4 w-4" strokeWidth={2} aria-hidden />
                Прикрепить картинки
              </span>
            </CapsuleButton>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {attachedIds.map((id) => (
              <div key={id} className="group relative">
                <MediaAssetThumb id={id} size={80} />
                <button
                  onClick={() => remove.mutate(id)}
                  disabled={remove.isPending}
                  aria-label="Открепить картинку"
                  className="absolute -right-1.5 -top-1.5 inline-flex h-6 w-6 items-center justify-center rounded-full border border-hairline bg-bg-elevated text-text-secondary shadow-sm hover:text-status-critical disabled:opacity-50"
                >
                  <X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {pickerOpen && (
        <MediaPickerSheet
          campaignId={campaignId}
          initial={attachedIds}
          onClose={() => setPickerOpen(false)}
          onSaved={() => qc.invalidateQueries({ queryKey: ["campaign", campaignId, "media"] })}
        />
      )}
    </Section>
  );
}

/* Шторка выбора медиа: галочками отмечаем ассеты, «Загрузить файл» добавляет
   свежий и сразу отмечает его. Сохраняется одной транзакцией. */
function MediaPickerSheet({
  campaignId,
  initial,
  onClose,
  onSaved,
}: {
  campaignId: number;
  initial: number[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["media-assets"], queryFn: mediaAssetsApi.list });
  const [selected, setSelected] = useState<Set<number>>(new Set(initial));
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => mediaAssetsApi.upload(file),
    onSuccess: (asset) => {
      setSelected((s) => new Set(s).add(asset.id));
      setError(null);
      qc.invalidateQueries({ queryKey: ["media-assets"] });
    },
    onError: (e: Error) => setError(e.message || "Не удалось загрузить"),
  });

  const save = useMutation({
    mutationFn: () => commentingApi.setMedia(campaignId, Array.from(selected)),
    onSuccess: () => {
      onSaved();
      onClose();
    },
    onError: (e: Error) => setError(e.message || "Не удалось сохранить"),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const items = useMemo(() => list.data ?? [], [list.data]);
  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)] lg:items-center lg:justify-center lg:p-8"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="mx-auto flex max-h-[85vh] w-full max-w-[440px] flex-col rounded-t-card border-t border-strong bg-bg-elevated lg:max-w-[640px] lg:rounded-card lg:border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 pb-3 pt-5">
          <div className="min-w-0">
            <h3 className="text-[17px] font-semibold text-text-primary">Картинки кампании</h3>
            <p className="text-[12px] text-text-tertiary">
              Отметьте те, что можно прикладывать · выбрано {selected.size}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-secondary hover:text-text-primary"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="flex items-center gap-2 px-5 pb-3">
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
          <CapsuleButton
            variant="secondary"
            className="w-auto px-4"
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
          >
            <span className="inline-flex items-center gap-1.5">
              <ImagePlus className="h-4 w-4" strokeWidth={2} aria-hidden />
              {upload.isPending ? "Загружаем…" : "Загрузить файл"}
            </span>
          </CapsuleButton>
        </div>

        <div className="flex-1 overflow-y-auto px-5 [scrollbar-width:thin]">
          {list.isLoading ? (
            <p className="py-8 text-center text-[13px] text-text-tertiary">Загрузка…</p>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-text-tertiary">
              У вас пока нет загруженных картинок. Загрузите первую кнопкой выше.
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-2 pb-2 sm:grid-cols-4 lg:grid-cols-5">
              {items.map((a) => {
                const active = selected.has(a.id);
                return (
                  <button
                    key={a.id}
                    onClick={() => toggle(a.id)}
                    className={`relative overflow-hidden rounded-chip border transition-colors ${
                      active ? "border-strong" : "border-hairline hover:border-strong"
                    }`}
                  >
                    <MediaAssetThumb id={a.id} size={120} />
                    {active && (
                      <span className="pointer-events-none absolute inset-0 flex items-end justify-end bg-accent/20 p-1.5">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-accent-on text-[11px] font-bold">
                          ✓
                        </span>
                      </span>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm("Удалить картинку из хранилища?")) {
                          mediaAssetsApi.remove(a.id).then(() => {
                            setSelected((s) => {
                              const n = new Set(s);
                              n.delete(a.id);
                              return n;
                            });
                            qc.invalidateQueries({ queryKey: ["media-assets"] });
                          });
                        }
                      }}
                      aria-label="Удалить из хранилища"
                      className="absolute left-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-full bg-bg-elevated/80 text-text-secondary hover:text-status-critical"
                    >
                      <Trash2 className="h-3 w-3" strokeWidth={2} aria-hidden />
                    </button>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-hairline px-5 pb-[calc(env(safe-area-inset-bottom)+14px)] pt-3 lg:pb-4">
          {error && <p className="mb-2 text-[12px] text-status-critical">{error}</p>}
          <CapsuleButton disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Сохраняем…" : `Сохранить (${selected.size})`}
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
