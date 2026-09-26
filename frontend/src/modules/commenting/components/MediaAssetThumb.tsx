import { useEffect, useState } from "react";
import { mediaAssetsApi } from "../../../shared/media";

/* Превью медиа-ассета: <img> не может пробросить наши Telegram-заголовки,
   поэтому тянем блоб через apiBlob и делаем ObjectURL. */
export function MediaAssetThumb({
  id,
  size = 72,
  onLoadError,
}: {
  id: number;
  size?: number;
  onLoadError?: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    mediaAssetsApi
      .blob(id)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => onLoadError?.());
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id, onLoadError]);

  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-chip border border-hairline bg-surface-1"
      style={{ width: size, height: size }}
    >
      {url ? (
        <img
          src={url}
          alt={`asset ${id}`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="h-full w-full animate-pulse bg-surface-2" />
      )}
    </div>
  );
}
