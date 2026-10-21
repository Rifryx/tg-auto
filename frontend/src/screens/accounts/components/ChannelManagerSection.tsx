import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bold,
  Code,
  Copy,
  EyeOff,
  ImagePlus,
  Italic,
  Link as LinkIcon,
  Megaphone,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Send,
  Strikethrough,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { accountsApi, mediaApi } from "../../../shared/accounts";
import { apiBlob } from "../../../shared/api";
import type { ProjectChannel } from "../../../shared/types";
import { Field, TextArea, TextInput, Toggle } from "../../../modules/commenting/components/ui";
import { CapsuleButton, Section } from "./ui";
import { useBulkJob } from "./useBulkJob";

/* Создание каналов/чатов аккаунтом + управление их постами
   («Управление аккаунтом», этап 1).

   Создание — bulk-action create_channel (пишет в project_channels, читаемые
   через GET /accounts/{id}/project-channels). Управление постами —
   manage_channel_post (send / pin / unpin / delete). */
export function ChannelManagerSection({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const channels = useQuery({
    queryKey: ["account", accountId, "project-channels"],
    queryFn: () => accountsApi.projectChannels(accountId),
    refetchInterval: 10_000, // create_channel выполняется воркером асинхронно
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["account", accountId, "project-channels"] });

  // Сверка списка с реальностью (воркер уберёт покинутые/удалённые) —
  // несколько отложенных рефетчей, т.к. воркер выполняет асинхронно.
  const sync = useMutation({
    mutationFn: () => accountsApi.syncProjectChannels(accountId),
    onSuccess: () => [2000, 5000, 9000].forEach((ms) => window.setTimeout(invalidate, ms)),
  });

  const [open, setOpen] = useState(false);
  const rows = channels.data ?? [];

  return (
    <Section
      title="Каналы и чаты аккаунта"
      action={
        rows.length > 0 ? (
          <button
            type="button"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 px-3 py-1.5 text-[12px] font-semibold text-text-secondary active:bg-surface-2 disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${sync.isPending ? "animate-spin" : ""}`}
              strokeWidth={2}
              aria-hidden
            />
            Синхронизировать
          </button>
        ) : undefined
      }
    >
      {rows.length === 0 && !open ? (
        <p className="mb-3 text-[13px] text-text-tertiary">
          Аккаунт ещё не создавал каналов.
        </p>
      ) : (
        <ul className="mb-3 flex flex-col gap-2">
          {rows.map((ch) => (
            <ChannelCard key={ch.id} accountId={accountId} channel={ch} onChanged={invalidate} />
          ))}
        </ul>
      )}

      {open ? (
        <CreateChannelForm
          accountId={accountId}
          onClose={() => setOpen(false)}
          onCreated={() => {
            invalidate();
            setOpen(false);
          }}
        />
      ) : (
        <CapsuleButton variant="secondary" onClick={() => setOpen(true)}>
          <span className="inline-flex items-center gap-2">
            <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
            Создать канал или чат
          </span>
        </CapsuleButton>
      )}
    </Section>
  );
}

function CreateChannelForm({
  accountId,
  onClose,
  onCreated,
}: {
  accountId: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [about, setAbout] = useState("");
  const [isMegagroup, setIsMegagroup] = useState(false);
  const [isPublic, setIsPublic] = useState(false);
  const [username, setUsername] = useState("");
  const [hidePrehistory, setHidePrehistory] = useState(false);
  const [enableReactions, setEnableReactions] = useState(true);
  const [firstPost, setFirstPost] = useState("");
  const [firstPostPin, setFirstPostPin] = useState(true);
  const [mediaId, setMediaId] = useState<number | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(false);
  const [photoId, setPhotoId] = useState<number | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [photoError, setPhotoError] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const photoRef = useRef<HTMLInputElement>(null);
  const job = useBulkJob(() => onCreated());

  useEffect(
    () => () => {
      if (mediaPreview) URL.revokeObjectURL(mediaPreview);
    },
    [mediaPreview],
  );
  useEffect(
    () => () => {
      if (photoPreview) URL.revokeObjectURL(photoPreview);
    },
    [photoPreview],
  );

  const onPickPhoto = async (file: File | undefined) => {
    if (!file) return;
    setPhotoUploading(true);
    setPhotoError(false);
    try {
      const asset = await mediaApi.upload(file);
      setPhotoId(asset.id);
      const blob = await apiBlob(`/media-assets/${asset.id}/blob`);
      if (photoPreview) URL.revokeObjectURL(photoPreview);
      setPhotoPreview(URL.createObjectURL(blob));
    } catch {
      setPhotoError(true);
    } finally {
      setPhotoUploading(false);
    }
  };

  // Оборачивает выделение в тексте маркерами эффекта (жирный/курсив/…).
  const wrap = (before: string, after: string, placeholder = "текст") => {
    const ta = taRef.current;
    if (!ta) return;
    const s = ta.selectionStart;
    const e = ta.selectionEnd;
    const sel = firstPost.slice(s, e) || placeholder;
    const next = firstPost.slice(0, s) + before + sel + after + firstPost.slice(e);
    setFirstPost(next);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(s + before.length, s + before.length + sel.length);
    });
  };

  const onPickMedia = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setUploadError(false);
    try {
      const asset = await mediaApi.upload(file);
      setMediaId(asset.id);
      const blob = await apiBlob(`/media-assets/${asset.id}/blob`);
      if (mediaPreview) URL.revokeObjectURL(mediaPreview);
      setMediaPreview(URL.createObjectURL(blob));
    } catch {
      setUploadError(true);
    } finally {
      setUploading(false);
    }
  };

  const clearMedia = () => {
    if (mediaPreview) URL.revokeObjectURL(mediaPreview);
    setMediaPreview(null);
    setMediaId(null);
  };

  const fmtBtn =
    "flex h-8 w-8 items-center justify-center rounded-chip border border-hairline text-text-secondary active:bg-surface-2 active:text-text-primary";

  const usernameValid = /^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(username.trim());
  const busy = job.state.phase === "running";
  const canCreate =
    title.trim().length > 0 &&
    !busy &&
    !photoUploading &&
    !uploading &&
    (!isPublic || usernameValid);
  return (
    <div className="card p-4">
      <input
        ref={photoRef}
        type="file"
        accept="image/*"
        onChange={(e) => {
          onPickPhoto(e.target.files?.[0]);
          e.target.value = "";
        }}
        className="hidden"
      />
      <div className="mb-4 flex items-center gap-3">
        <button
          type="button"
          onClick={() => photoRef.current?.click()}
          disabled={photoUploading}
          aria-label="Фото канала"
          className="relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-hairline bg-surface-1 active:border-strong disabled:opacity-50"
        >
          {photoPreview ? (
            <img src={photoPreview} alt="" className="h-full w-full object-cover" />
          ) : (
            <ImagePlus className="h-6 w-6 text-accent" strokeWidth={1.6} aria-hidden />
          )}
        </button>
        <div className="min-w-0">
          <p className="text-[14px] text-text-primary">
            {isMegagroup ? "Фото чата" : "Фото канала"}
          </p>
          <p className="text-[12px] text-text-tertiary">
            {photoUploading
              ? "Загружаем…"
              : photoPreview
                ? "Нажмите, чтобы заменить"
                : "Необязательно"}
          </p>
          {photoPreview && (
            <button
              type="button"
              onClick={() => {
                if (photoPreview) URL.revokeObjectURL(photoPreview);
                setPhotoPreview(null);
                setPhotoId(null);
              }}
              className="mt-0.5 text-[12px] text-status-critical active:opacity-70"
            >
              Убрать фото
            </button>
          )}
        </div>
      </div>
      {photoError && (
        <p className="mb-3 px-1 text-[12px] text-status-critical">Не удалось загрузить фото.</p>
      )}
      <Field label={isMegagroup ? "Название чата" : "Название канала"}>
        <TextInput value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} />
      </Field>
      <Field label="Описание">
        <TextArea value={about} onChange={(e) => setAbout(e.target.value)} maxLength={255} />
      </Field>
      <label className="mb-3 flex items-center justify-between px-1">
        <span className="text-[14px] text-text-secondary">Супергруппа (чат), а не канал</span>
        <Toggle checked={isMegagroup} onChange={setIsMegagroup} label="Супергруппа" />
      </label>

      <label className="mb-1 flex items-center justify-between px-1">
        <span className="text-[14px] text-text-secondary">
          Публичный (есть ссылка t.me/…)
        </span>
        <Toggle checked={isPublic} onChange={setIsPublic} label="Публичный" />
      </label>
      {isPublic ? (
        <Field label="Публичная ссылка">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0 text-[14px] text-text-tertiary">t.me/</span>
            <TextInput
              value={username}
              onChange={(e) => setUsername(e.target.value.replace(/[^a-zA-Z0-9_]/g, ""))}
              maxLength={32}
              placeholder="username"
            />
          </div>
          {username.length > 0 && !usernameValid && (
            <p className="mt-1 px-1 text-[12px] text-status-critical">
              5–32 символа, латиница/цифры/_, начинается с буквы.
            </p>
          )}
        </Field>
      ) : (
        <p className="mb-3 px-1 text-[12px] text-text-tertiary">
          Приватный: без публичной ссылки, вступление только по пригласительной.
        </p>
      )}
      {isMegagroup && (
        <label className="mb-1 flex items-center justify-between px-1">
          <span className="text-[14px] text-text-secondary">
            Скрыть историю для новых участников
          </span>
          <Toggle
            checked={hidePrehistory}
            onChange={setHidePrehistory}
            label="Скрыть историю"
          />
        </label>
      )}
      <label className="mb-3 flex items-center justify-between px-1">
        <span className="text-[14px] text-text-secondary">Разрешить реакции</span>
        <Toggle checked={enableReactions} onChange={setEnableReactions} label="Реакции" />
      </label>

      <Field label="Первый пост (необязательно)">
        <div className="mb-2 flex flex-wrap gap-1.5">
          <button type="button" onClick={() => wrap("**", "**")} className={fmtBtn} aria-label="Жирный">
            <Bold className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
          <button type="button" onClick={() => wrap("__", "__")} className={fmtBtn} aria-label="Курсив">
            <Italic className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
          <button type="button" onClick={() => wrap("~~", "~~")} className={fmtBtn} aria-label="Зачёркнутый">
            <Strikethrough className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
          <button type="button" onClick={() => wrap("||", "||")} className={fmtBtn} aria-label="Скрытый (спойлер)">
            <EyeOff className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
          <button type="button" onClick={() => wrap("`", "`")} className={fmtBtn} aria-label="Моноширинный">
            <Code className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
          <button type="button" onClick={() => wrap("[", "](https://)", "ссылка")} className={fmtBtn} aria-label="Ссылка">
            <LinkIcon className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
        </div>
        <textarea
          ref={taRef}
          value={firstPost}
          onChange={(e) => setFirstPost(e.target.value)}
          placeholder="Текст первого поста. Выдели фрагмент и нажми эффект."
          className="w-full min-h-[120px] resize-y rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[15px] leading-relaxed text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
        />
        <p className="mt-1 px-1 text-[12px] text-text-tertiary">
          **жирный** · __курсив__ · ~~зачёркнутый~~ · ||скрытый|| · `моно` · [текст](ссылка)
        </p>

        <input
          ref={fileRef}
          type="file"
          accept="image/*,video/*"
          onChange={(e) => {
            onPickMedia(e.target.files?.[0]);
            e.target.value = "";
          }}
          className="hidden"
        />
        {mediaPreview ? (
          <div className="mt-2 flex items-center gap-3 rounded-chip border border-hairline bg-surface-1 p-2">
            <img src={mediaPreview} alt="" className="h-14 w-14 rounded-lg object-cover" />
            <span className="min-w-0 flex-1 truncate text-[13px] text-text-secondary">
              Медиа прикреплено
            </span>
            <button
              type="button"
              onClick={clearMedia}
              aria-label="Убрать медиа"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-hairline text-text-tertiary active:text-text-primary"
            >
              <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-chip border border-dashed border-hairline bg-surface-1 py-2.5 text-[13px] text-text-secondary active:border-strong disabled:opacity-50"
          >
            <ImagePlus className="h-4 w-4 text-accent" strokeWidth={1.6} aria-hidden />
            {uploading ? "Загружаем…" : "Прикрепить фото/видео"}
          </button>
        )}
        {uploadError && (
          <p className="mt-1 px-1 text-[12px] text-status-critical">Не удалось загрузить медиа.</p>
        )}

        <label className="mt-3 flex items-center justify-between px-1">
          <span className="text-[14px] text-text-secondary">Закрепить первый пост</span>
          <Toggle checked={firstPostPin} onChange={setFirstPostPin} label="Закрепить пост" />
        </label>
      </Field>

      {job.state.phase === "failed" && (
        <p className="mb-2 text-[12px] text-status-critical">
          {job.state.error ?? "Не удалось создать."}
        </p>
      )}
      {busy && job.state.slow && (
        <p className="mb-2 text-[12px] text-text-tertiary">
          Долго выполняется. Проверьте, что воркер запущен, а у аккаунта живой
          прокси и активная сессия.
        </p>
      )}

      <div className="flex gap-2">
        <CapsuleButton variant="secondary" onClick={onClose}>
          Отмена
        </CapsuleButton>
        <CapsuleButton
          variant="accent"
          disabled={!canCreate}
          onClick={() =>
            job.run("create_channel", [accountId], {
              title: title.trim(),
              about: about.trim(),
              is_megagroup: isMegagroup,
              is_public: isPublic,
              public_username: isPublic ? username.trim() : null,
              hide_prehistory: isMegagroup && hidePrehistory,
              enable_reactions: enableReactions,
              first_post: firstPost.trim() || null,
              first_post_media_id: mediaId,
              first_post_markdown: true,
              first_post_pin: firstPostPin,
              photo_media_id: photoId,
            })
          }
        >
          <span className="inline-flex items-center gap-2">
            <Megaphone className="h-4 w-4" strokeWidth={2} aria-hidden />
            {busy ? "Создаём…" : "Создать"}
          </span>
        </CapsuleButton>
      </div>
    </div>
  );
}

/* Копируемая ссылка (публичная t.me/… или пригласительная). */
function CopyLink({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="mb-1 px-1 text-[12px] text-text-tertiary">{label}</p>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard
            ?.writeText(value)
            .then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => {});
        }}
        className="flex w-full items-center gap-2 rounded-chip border border-hairline bg-surface-2 px-3 py-2 text-left active:bg-surface-1"
      >
        <span className="min-w-0 flex-1 truncate text-[13px] text-text-primary nums">
          {value}
        </span>
        <Copy
          className={`h-3.5 w-3.5 shrink-0 ${copied ? "text-status-active" : "text-text-tertiary"}`}
          strokeWidth={1.8}
          aria-hidden
        />
      </button>
      {copied && (
        <p className="mt-0.5 px-1 text-[11px] text-status-active">Скопировано</p>
      )}
    </div>
  );
}

/* Карточка одного созданного канала + управление его постами. */
function ChannelCard({
  accountId,
  channel,
  onChanged,
}: {
  accountId: number;
  channel: ProjectChannel;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [post, setPost] = useState("");
  const [pinNew, setPinNew] = useState(false);
  const [deleteId, setDeleteId] = useState("");
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState(false);
  const [confirmDelCh, setConfirmDelCh] = useState(false);
  const cardPhotoRef = useRef<HTMLInputElement>(null);
  const job = useBulkJob(() => onChanged());

  const base = { channel_tg_id: channel.channel_tg_id, channel_access_hash: channel.channel_access_hash };
  const busy = job.state.phase === "running";

  // Сменить аватар канала/чата: грузим фото в media-assets → manage_channel_post
  // mode=set_photo (воркер ставит EditPhoto).
  const onPickCardPhoto = async (file: File | undefined) => {
    if (!file) return;
    setPhotoBusy(true);
    setPhotoError(false);
    try {
      const asset = await mediaApi.upload(file);
      await job.run("manage_channel_post", [accountId], {
        ...base,
        mode: "set_photo",
        photo_media_id: asset.id,
      });
    } catch {
      setPhotoError(true);
    } finally {
      setPhotoBusy(false);
    }
  };

  return (
    <li className="rounded-card border border-hairline bg-surface-1">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <Megaphone className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.6} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] text-text-primary">
            {channel.title}
            {channel.is_megagroup && (
              <span className="ml-1.5 text-[12px] text-text-tertiary">· чат</span>
            )}
          </p>
          <p className="truncate text-[12px] text-text-tertiary">
            {channel.username
              ? `@${channel.username}`
              : channel.invite_link
                ? "приватный · есть ссылка"
                : "приватный"}
            {channel.is_pinned && (
              <span className="ml-1.5 inline-flex items-center gap-0.5">
                · <Pin className="inline h-3 w-3" strokeWidth={1.8} aria-hidden /> в списке
              </span>
            )}
          </p>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-hairline p-4">
          <input
            ref={cardPhotoRef}
            type="file"
            accept="image/*"
            onChange={(e) => {
              onPickCardPhoto(e.target.files?.[0]);
              e.target.value = "";
            }}
            className="hidden"
          />
          <div className="mb-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => cardPhotoRef.current?.click()}
              disabled={photoBusy || busy}
              aria-label="Сменить фото канала"
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface-2 text-text-tertiary active:border-strong disabled:opacity-50"
            >
              <ImagePlus className="h-5 w-5" strokeWidth={1.6} aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => cardPhotoRef.current?.click()}
              disabled={photoBusy || busy}
              className="text-[13px] text-text-secondary active:text-text-primary disabled:opacity-50"
            >
              {photoBusy ? "Ставим фото…" : `Сменить фото ${channel.is_megagroup ? "чата" : "канала"}`}
            </button>
          </div>
          {photoError && (
            <p className="mb-3 px-1 text-[12px] text-status-critical">
              Не удалось обновить фото.
            </p>
          )}

          {(channel.username || channel.invite_link) && (
            <div className="mb-3 flex flex-col gap-2">
              {channel.username && (
                <CopyLink
                  label="Публичная ссылка"
                  value={`https://t.me/${channel.username}`}
                />
              )}
              {channel.invite_link && (
                <CopyLink label="Пригласительная ссылка" value={channel.invite_link} />
              )}
            </div>
          )}

          <div className="mb-3 flex items-center justify-between rounded-chip border border-hairline bg-surface-2 px-3 py-2">
            <span className="inline-flex items-center gap-1.5 text-[13px] text-text-secondary">
              <Pin className="h-3.5 w-3.5 text-text-tertiary" strokeWidth={1.8} aria-hidden />
              Закрепить {channel.is_megagroup ? "чат" : "канал"} в списке
            </span>
            <Toggle
              checked={channel.is_pinned}
              disabled={busy}
              onChange={(next) =>
                job.run("manage_channel_post", [accountId], {
                  ...base,
                  mode: next ? "pin_dialog" : "unpin_dialog",
                })
              }
              label="Закрепить в списке диалогов"
            />
          </div>

          <Field label="Новый пост">
            <TextArea value={post} onChange={(e) => setPost(e.target.value)} placeholder="Текст поста" />
          </Field>
          <label className="mb-3 flex items-center justify-between px-1">
            <span className="text-[14px] text-text-secondary">Закрепить после отправки</span>
            <Toggle checked={pinNew} onChange={setPinNew} label="Закрепить" />
          </label>
          <CapsuleButton
            variant="accent"
            disabled={post.trim().length === 0 || busy}
            onClick={() =>
              job.run("manage_channel_post", [accountId], {
                ...base,
                mode: "send",
                text: post.trim(),
                pin_after_send: pinNew,
              }).then(() => setPost(""))
            }
          >
            <span className="inline-flex items-center gap-2">
              <Send className="h-4 w-4" strokeWidth={2} aria-hidden />
              {busy ? "Отправляем…" : "Опубликовать"}
            </span>
          </CapsuleButton>

          {channel.pinned_message_id != null && (
            <button
              onClick={() =>
                job.run("manage_channel_post", [accountId], {
                  ...base,
                  mode: "unpin",
                  message_id: channel.pinned_message_id,
                })
              }
              disabled={busy}
              className="mt-2 flex items-center gap-1.5 text-[13px] text-text-secondary active:text-text-primary"
            >
              <PinOff className="h-4 w-4" strokeWidth={1.8} aria-hidden />
              Открепить текущий пост
            </button>
          )}

          <div className="mt-3 border-t border-hairline pt-3">
            <Field label="Удалить пост по id">
              <div className="flex gap-2">
                <TextInput
                  value={deleteId}
                  onChange={(e) => setDeleteId(e.target.value.replace(/\D/g, ""))}
                  inputMode="numeric"
                  placeholder="id сообщения"
                />
                <button
                  onClick={() =>
                    job
                      .run("manage_channel_post", [accountId], {
                        ...base,
                        mode: "delete",
                        message_id: Number(deleteId),
                      })
                      .then(() => setDeleteId(""))
                  }
                  disabled={deleteId.length === 0 || busy}
                  aria-label="Удалить пост"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-hairline text-status-critical disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
            </Field>
          </div>

          {job.state.phase === "failed" && (
            <p className="mt-2 text-[12px] text-status-critical">
              {job.state.error ?? "Не удалось выполнить."}
            </p>
          )}
          {job.state.phase === "done" && (
            <p className="mt-2 text-[12px] text-status-active">Готово.</p>
          )}

          <div className="mt-3 border-t border-hairline pt-3">
            {confirmDelCh ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    job
                      .run("manage_channel_post", [accountId], {
                        ...base,
                        mode: "delete_channel",
                      })
                      .then(() => onChanged())
                  }
                  disabled={busy}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-pill bg-status-critical px-3 py-2 text-[13px] font-semibold text-white active:opacity-80 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                  {busy ? "Удаляем…" : `Точно удалить ${channel.is_megagroup ? "чат" : "канал"}?`}
                </button>
                <button
                  onClick={() => setConfirmDelCh(false)}
                  disabled={busy}
                  className="rounded-pill border border-hairline px-3 py-2 text-[13px] text-text-secondary active:bg-surface-2"
                >
                  Отмена
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelCh(true)}
                className="flex items-center gap-1.5 text-[13px] text-status-critical active:opacity-70"
              >
                <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                Удалить {channel.is_megagroup ? "чат" : "канал"}
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
