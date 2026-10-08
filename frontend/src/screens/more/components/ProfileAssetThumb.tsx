import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";
import { profileAssetsApi } from "../api";

/* Превью аватара из пула оформления: <img> не может пробросить наши
   Telegram-заголовки, поэтому тянем блоб через apiBlob и делаем ObjectURL
   (как MediaAssetThumb). Квадратная плитка под галерею. */
export function ProfileAssetThumb({
  id,
  className = "",
}: {
  id: number;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    setFailed(false);
    setUrl(null);
    profileAssetsApi
      .blob(id)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id]);

  return (
    <div
      className={`relative aspect-square w-full overflow-hidden rounded-chip border border-hairline bg-surface-2 ${className}`}
    >
      {url ? (
        <img
          src={url}
          alt={`Аватар #${id}`}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : failed ? (
        <div className="flex h-full w-full items-center justify-center text-text-tertiary">
          <ImageOff className="h-5 w-5" strokeWidth={1.6} aria-hidden />
        </div>
      ) : (
        <div className="h-full w-full animate-pulse bg-surface-1" />
      )}
    </div>
  );
}
