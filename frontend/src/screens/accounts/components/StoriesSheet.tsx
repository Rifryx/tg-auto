import { ImagePlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { mediaApi } from "../../../shared/accounts";
import { apiBlob } from "../../../shared/api";
import { Field, TextArea } from "../../../modules/commenting/components/ui";
import { Select } from "../../../shared/Select";
import { CapsuleButton } from "./ui";

const PRIVACY = [
  { value: "everybody", label: "Все" },
  { value: "contacts_only", label: "Контакты" },
  { value: "close_friends", label: "Близкие друзья" },
  { value: "nobody", label: "Никто" },
];

const PERIOD = [
  { value: "21600", label: "6 часов" },
  { value: "43200", label: "12 часов" },
  { value: "86400", label: "24 часа" },
  { value: "172800", label: "48 часов" },
];

/* Конфигуратор массовой публикации Stories (publish_story).
 *
 * Загружает одно изображение в media-assets (получает media_asset_id), даёт
 * задать подпись, приватность и срок жизни, и публикует историю от лица каждого
 * выбранного аккаунта (каждый льёт медиа своим клиентом/прокси). */
export function StoriesSheet({
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
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(false);
  const [assetId, setAssetId] = useState<number | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [privacy, setPrivacy] = useState("everybody");
  const [period, setPeriod] = useState("86400");

  // Чистим ObjectURL превью при размонтировании/замене.
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setUploadError(false);
    try {
      const asset = await mediaApi.upload(file);
      setAssetId(asset.id);
      const blob = await apiBlob(`/media-assets/${asset.id}/blob`);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch {
      setUploadError(true);
    } finally {
      setUploading(false);
    }
  };

  const canApply = assetId != null && !busy && !uploading;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center px-3 pb-4 pt-4 lg:items-center lg:px-4 lg:pb-4 bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onCancel}
    >
      {/* flex-col + max-h: шапка/действия закреплены сверху/снизу, тело
         прокручивается — на коротких экранах диалог раньше выезжал за
         область видимости (кнопка «Опубликовать» уходила за край). */}
      <div
        className="flex max-h-[calc(100dvh-32px)] w-full max-w-[420px] flex-col rounded-card border border-strong bg-bg-elevated"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 pb-3 pt-5">
          <div className="min-w-0">
            <h3 className="text-[18px] font-semibold text-text-primary">Публикация Stories</h3>
            <p className="mt-0.5 text-[13px] text-text-secondary">
              Одна история от лица {count} акк. Каждый публикует своим клиентом.
            </p>
          </div>
          <button
            onClick={onCancel}
            aria-label="Закрыть"
            className="shrink-0 text-text-tertiary active:text-text-primary"
          >
            <X className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 [scrollbar-width:thin]">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            onChange={(e) => {
              onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
            className="hidden"
          />

          {previewUrl ? (
            <button
              onClick={() => fileRef.current?.click()}
              className="flex w-full justify-center"
              aria-label="Заменить изображение"
            >
              <img
                src={previewUrl}
                alt=""
                className="max-h-[180px] rounded-card border border-hairline object-contain"
              />
            </button>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="flex min-h-[100px] w-full flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-hairline bg-surface-1 p-4 text-center active:border-strong disabled:opacity-50"
            >
              <ImagePlus className="h-7 w-7 text-accent" strokeWidth={1.5} aria-hidden />
              <span className="text-[14px] font-semibold text-text-primary">
                {uploading ? "Загружаем…" : "Выбрать изображение"}
              </span>
            </button>
          )}
          {uploadError && (
            <p className="mt-2 text-[12px] text-status-critical">Не удалось загрузить изображение.</p>
          )}

          <div className="mt-4">
            <Field label="Подпись (опц.)">
              <TextArea value={caption} onChange={(e) => setCaption(e.target.value)} rows={2} />
            </Field>
          </div>

          <div className="flex gap-2">
            <div className="flex-1">
              <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Кто видит</p>
              <Select value={privacy} onChange={setPrivacy} options={PRIVACY} />
            </div>
            <div className="flex-1">
              <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Срок</p>
              <Select value={period} onChange={setPeriod} options={PERIOD} />
            </div>
          </div>
        </div>

        <div
          className="flex flex-col gap-2 border-t border-hairline px-5 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 14px)" }}
        >
          <CapsuleButton
            variant={canApply ? "accent" : "secondary"}
            disabled={!canApply}
            onClick={() =>
              onApply({
                media_asset_id: assetId,
                caption,
                privacy,
                period: Number(period),
              })
            }
          >
            {busy ? "Публикуем…" : "Опубликовать"}
          </CapsuleButton>
          <CapsuleButton variant="secondary" onClick={onCancel} disabled={busy}>
            Отмена
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}
