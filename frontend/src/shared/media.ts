import { api, apiBlob } from "./api";

export interface MediaAsset {
  id: number;
  mime: string;
  size_bytes: number;
  sha256: string;
  filename: string | null;
  created_at: string;
}

/* Media-assets владельца — используются в кампаниях (E4.1 attach_image) и
   раньше в Stories (bulk). Хранилище общее у пользователя. */
export const mediaAssetsApi = {
  list: () => api.get<MediaAsset[]>("/media-assets"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<MediaAsset>("/media-assets", form);
  },
  remove: (id: number) => api.del<void>(`/media-assets/${id}`),
  blob: (id: number) => apiBlob(`/media-assets/${id}/blob`),
};
