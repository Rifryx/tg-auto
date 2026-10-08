import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ProfileAsset, ProfileAssetKind } from "../../shared/types";
import { showToast } from "../../shared/toast";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  TextArea,
  TextInput,
} from "../../modules/commenting/components/ui";
import { Section } from "../accounts/components/ui";
import { profileAssetsApi, type ProfileAssetBody } from "./api";
import { ProfileAssetThumb } from "./components/ProfileAssetThumb";
import { BackHeader } from "./PersonasScreen";

const KINDS: { value: ProfileAssetKind; label: string }[] = [
  { value: "avatar", label: "Аватары" },
  { value: "first_name", label: "Имена" },
  { value: "last_name", label: "Фамилии" },
  { value: "bio", label: "BIO" },
  { value: "username_template", label: "Username" },
];

const HINT: Record<ProfileAssetKind, string> = {
  avatar: "Загрузите несколько изображений — распределятся по аккаунтам случайно.",
  first_name: "По одному имени в строке. Распределяются случайно по аккаунтам.",
  last_name: "По одной фамилии в строке.",
  bio: "По одному варианту «о себе» в строке — рандомайзер BIO.",
  username_template: "Шаблоны: {n} заменяется на случайное число, напр. trader_{n}.",
};

/* Уменьшает картинку до 512px и возвращает ЧИСТЫЙ base64 (без data:-префикса)
   для ProfileAssetCreate.binary_b64. */
async function fileToBase64(file: File): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result as string);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("bad image"));
    el.src = dataUrl;
  });
  const max = 512;
  const scale = Math.min(1, max / Math.max(img.width, img.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  canvas.getContext("2d")?.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85).split(",")[1] ?? "";
}

export function ProfileAssetsScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [kind, setKind] = useState<ProfileAssetKind>("avatar");
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");
  const [toDelete, setToDelete] = useState<ProfileAsset | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const list = useQuery({
    queryKey: ["profile-assets", kind],
    queryFn: () => profileAssetsApi.list(kind),
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["profile-assets", kind] });
  const tagList = () =>
    tags.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);

  const addMany = useMutation({
    mutationFn: async (bodies: ProfileAssetBody[]) => {
      for (const b of bodies) await profileAssetsApi.create(b);
      return bodies.length;
    },
    onSuccess: (n) => {
      showToast(`Добавлено: ${n}`, "success");
      setText("");
      setDescription("");
      invalidate();
    },
    onError: () => showToast("Не удалось добавить", "error"),
  });

  const remove = useMutation({
    mutationFn: (id: number) => profileAssetsApi.remove(id),
    onSuccess: () => {
      setToDelete(null);
      invalidate();
    },
  });

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const t = tagList();
    const desc = description.trim() || null;
    try {
      const bodies: ProfileAssetBody[] = [];
      for (const f of Array.from(files)) {
        bodies.push({
          kind: "avatar",
          binary_b64: await fileToBase64(f),
          mime: "image/jpeg",
          tags: t,
          description: desc,
        });
      }
      addMany.mutate(bodies);
    } catch {
      showToast("Не удалось обработать изображения", "error");
    }
  };

  const addText = () => {
    const t = tagList();
    const bodies: ProfileAssetBody[] = text
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((value) => ({ kind, value, tags: t }));
    if (bodies.length === 0) return;
    addMany.mutate(bodies);
  };

  const rows = list.data ?? [];

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Пул оформления" onBack={() => navigate("/more")} />

      <div className="-mx-5 mb-4 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {KINDS.map((k) => (
          <button
            key={k.value}
            onClick={() => setKind(k.value)}
            className={`min-h-[36px] shrink-0 rounded-pill border px-4 text-[14px] font-medium transition-colors ${
              kind === k.value
                ? "border-strong bg-surface-2 text-text-primary"
                : "border-hairline bg-surface-1 text-text-secondary"
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <Section title="Добавить в пул">
        <p className="mb-3 text-[12px] text-text-tertiary">{HINT[kind]}</p>

        {kind === "avatar" ? (
          <>
            <div className="mb-3">
              <Field label="Описание (опц.)">
                <TextInput
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Напр.: мужские, нейтральный фон"
                />
              </Field>
              <p className="-mt-2 px-1 text-[11px] text-text-tertiary">
                Применится к изображениям, которые выберете ниже.
              </p>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => {
                onFiles(e.target.files);
                e.target.value = "";
              }}
              className="hidden"
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={addMany.isPending}
              className="flex min-h-[120px] w-full flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-hairline bg-surface-1 p-4 text-center active:border-strong disabled:opacity-50"
            >
              <ImagePlus className="h-7 w-7 text-accent" strokeWidth={1.5} aria-hidden />
              <span className="text-[14px] font-semibold text-text-primary">
                {addMany.isPending ? "Загружаем…" : "Выбрать изображения"}
              </span>
              <span className="text-[11px] text-text-tertiary">можно несколько сразу</span>
            </button>
          </>
        ) : (
          <TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder={HINT[kind]}
          />
        )}

        <div className="mt-3">
          <Field label="Теги (опц., через запятую)">
            <TextInput
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="ru, мужское"
            />
          </Field>
        </div>

        {kind !== "avatar" && (
          <CapsuleButton
            variant={text.trim() ? "accent" : "secondary"}
            disabled={!text.trim() || addMany.isPending}
            onClick={addText}
          >
            <span className="inline-flex items-center gap-2">
              <UploadCloud className="h-4 w-4" strokeWidth={2} aria-hidden />
              {addMany.isPending ? "Добавляем…" : "Добавить в пул"}
            </span>
          </CapsuleButton>
        )}
      </Section>

      <Section title={`В пуле: ${rows.length}`}>
        {list.isLoading ? (
          <p className="text-[13px] text-text-tertiary">Загрузка…</p>
        ) : rows.length === 0 ? (
          <p className="text-[13px] text-text-tertiary">Пока пусто.</p>
        ) : kind === "avatar" ? (
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4 lg:grid-cols-5">
            {rows.map((a) => (
              <figure key={a.id} className="group relative">
                <ProfileAssetThumb id={a.id} />
                <figcaption className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-0.5 rounded-b-chip bg-gradient-to-t from-black/75 to-transparent px-2 pb-1.5 pt-5 text-[11px] text-white">
                  {a.description && (
                    <span className="truncate font-medium" title={a.description}>
                      {a.description}
                    </span>
                  )}
                  <span className="flex items-center justify-between gap-1">
                    <span className="truncate">{a.used_count}×</span>
                    {a.tags.length > 0 && (
                      <span className="truncate opacity-80">{a.tags.join(", ")}</span>
                    )}
                  </span>
                </figcaption>
                <button
                  onClick={() => setToDelete(a)}
                  aria-label="Удалить изображение"
                  className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-bg-elevated/85 text-text-secondary shadow-sm backdrop-blur active:text-status-critical"
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
                </button>
              </figure>
            ))}
          </div>
        ) : (
          <ul className="flex flex-col">
            {rows.map((a, i) => (
              <li
                key={a.id}
                className={`flex items-center gap-3 py-2.5 ${i > 0 ? "border-t border-hairline" : ""}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] text-text-primary">{a.value}</p>
                  <p className="text-[12px] text-text-tertiary">
                    применён {a.used_count}×{a.tags.length > 0 && ` · ${a.tags.join(", ")}`}
                  </p>
                </div>
                <button
                  onClick={() => setToDelete(a)}
                  aria-label="Удалить"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить ассет?"
        message="Он больше не будет распределяться по аккаунтам."
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
