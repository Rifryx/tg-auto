import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Send, ExternalLink } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { openExternal } from "../../shared/tg";
import { showToast } from "../../shared/toast";
import { useAppContent } from "./AboutScreen";
import { supportApi } from "./api";
import { BackHeader } from "./PersonasScreen";

export function SupportScreen() {
  const navigate = useNavigate();
  const { data: content } = useAppContent();
  const support = content?.support;

  const managerUrl =
    support?.manager_url?.trim() ||
    (support?.manager_username ? `https://t.me/${support.manager_username}` : "");

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Поддержка" onBack={() => navigate("/more")} />

      {support?.intro && (
        <p className="mb-4 px-1 text-[14px] leading-relaxed text-text-secondary">
          {support.intro}
        </p>
      )}

      {managerUrl && (
        <button
          type="button"
          onClick={() => openExternal(managerUrl)}
          className="mb-4 flex w-full items-center gap-3 rounded-card border border-hairline bg-surface-1 px-4 py-3.5 text-left active:bg-surface-2"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
            <ExternalLink className="h-4.5 w-4.5" strokeWidth={1.8} aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold text-text-primary">Написать в ЛС</p>
            <p className="truncate text-[12px] text-text-tertiary">
              Открыть личный чат с менеджером
            </p>
          </div>
        </button>
      )}

      {support?.in_app_enabled !== false ? (
        <SupportChat />
      ) : (
        !managerUrl && (
          <p className="px-1 text-[13px] text-text-tertiary">
            Контакты поддержки пока не настроены.
          </p>
        )
      )}
    </div>
  );
}

function SupportChat() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const thread = useQuery({
    queryKey: ["support", "thread"],
    queryFn: supportApi.thread,
    refetchInterval: 5000, // ждём ответ менеджера
  });

  const send = useMutation({
    mutationFn: (t: string) => supportApi.send(t),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["support", "thread"] });
    },
    onError: () => showToast("Не удалось отправить", "error"),
  });

  const messages = thread.data?.messages ?? [];

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  return (
    <div className="card flex flex-col p-0">
      <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
        <MessageCircle className="h-4 w-4 text-accent" strokeWidth={1.8} aria-hidden />
        <span className="text-[14px] font-semibold text-text-primary">Чат с поддержкой</span>
      </div>

      <div ref={listRef} className="flex max-h-[50vh] min-h-[160px] flex-col gap-2 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <p className="text-[13px] text-text-tertiary">
            Напишите сообщение — менеджер ответит здесь же.
          </p>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={[
                "max-w-[85%] rounded-2xl px-3.5 py-2 text-[14px] leading-relaxed",
                m.direction === "user"
                  ? "self-end bg-accent text-accent-on"
                  : "self-start bg-surface-2 text-text-primary",
              ].join(" ")}
            >
              <p className="whitespace-pre-wrap break-words">{m.text}</p>
              {m.created_at && (
                <p
                  className={`mt-0.5 text-[10px] ${
                    m.direction === "user" ? "text-accent-on/70" : "text-text-tertiary"
                  }`}
                >
                  {new Date(m.created_at).toLocaleTimeString("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              )}
            </div>
          ))
        )}
      </div>

      <div className="flex items-end gap-2 border-t border-hairline p-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={1}
          placeholder="Сообщение…"
          className="min-h-[44px] max-h-32 flex-1 resize-none rounded-chip border border-hairline bg-surface-1 px-4 py-2.5 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
        />
        <button
          type="button"
          disabled={!text.trim() || send.isPending}
          onClick={() => send.mutate(text.trim())}
          aria-label="Отправить"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-accent-on active:opacity-80 disabled:opacity-50"
        >
          <Send className="h-5 w-5" strokeWidth={2} aria-hidden />
        </button>
      </div>
    </div>
  );
}
