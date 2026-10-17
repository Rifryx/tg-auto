import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Megaphone, Pin, PinOff, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
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

  const [open, setOpen] = useState(false);
  const rows = channels.data ?? [];

  return (
    <Section title="Каналы и чаты аккаунта">
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
  const job = useBulkJob(() => onCreated());

  const usernameValid = /^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(username.trim());
  const busy = job.state.phase === "running";
  const canCreate =
    title.trim().length > 0 && !busy && (!isPublic || usernameValid);
  return (
    <div className="card p-4">
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

      <Field label="Первый пост (необязательно, будет закреплён)">
        <TextArea
          value={firstPost}
          onChange={(e) => setFirstPost(e.target.value)}
          placeholder="Текст первого поста — закрепится автоматически"
        />
      </Field>

      {job.state.phase === "failed" && (
        <p className="mb-2 text-[12px] text-status-critical">
          {job.state.error ?? "Не удалось создать."}
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
              pin_first_post: firstPost.trim() || null,
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
  const job = useBulkJob(() => onChanged());

  const base = { channel_tg_id: channel.channel_tg_id, channel_access_hash: channel.channel_access_hash };
  const busy = job.state.phase === "running";

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
            {channel.username ? `@${channel.username}` : "приватный"}
            {channel.pinned_message_id != null && (
              <span className="ml-1.5 inline-flex items-center gap-0.5">
                · <Pin className="inline h-3 w-3" strokeWidth={1.8} aria-hidden /> закреплён
              </span>
            )}
          </p>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-hairline p-4">
          {!channel.username && channel.invite_link && (
            <div className="mb-3">
              <p className="mb-1 px-1 text-[12px] text-text-tertiary">
                Пригласительная ссылка
              </p>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard?.writeText(channel.invite_link!).catch(() => {});
                }}
                className="flex w-full items-center gap-2 rounded-chip border border-hairline bg-surface-2 px-3 py-2 text-left active:bg-surface-1"
              >
                <span className="min-w-0 flex-1 truncate text-[13px] text-text-primary nums">
                  {channel.invite_link}
                </span>
                <Copy className="h-3.5 w-3.5 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
              </button>
            </div>
          )}

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
        </div>
      )}
    </li>
  );
}
