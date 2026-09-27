import { useQuery } from "@tanstack/react-query";
import { Filter } from "lucide-react";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { timeAgo } from "../../shared/format";
import { parsingApi } from "./api";
import type { ParsedList } from "./types";

/* Модуль «Парсинг» — самостоятельный сервис (docs/priming-spec §8).
   Хранит спарсенные списки; Прайминг импортирует их через
   POST /modules/priming/campaigns/:id/targets/import-list. */

const SOURCE_LABEL: Record<ParsedList["source_kind"], string> = {
  chat_messages: "Сообщения чата",
  chat_members: "Участники чата",
  manual_list: "Ручной список",
  upload_csv: "CSV",
};

export function ParsingListsScreen() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parsing", "lists"],
    queryFn: parsingApi.list,
    refetchInterval: 10_000,
  });

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader title="Парсинг" />
      <p className="mb-4 text-[13px] text-text-secondary">
        Собранные списки аудитории. Прайминг и другие модули берут отсюда,
        а не парсят повторно.
      </p>

      {isLoading && (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-20 animate-pulse bg-surface-2" />
          ))}
        </div>
      )}
      {isError && (
        <p className="text-[14px] text-status-critical">
          Не удалось загрузить списки.
        </p>
      )}
      {data && data.length === 0 && (
        <EmptyState
          icon={Filter}
          title="Пока нет спарсенных списков"
          hint="Запуск парсера — на экране кампании прайминга или через API /modules/parsing/lists/run/chat-messages."
        />
      )}
      {data && data.length > 0 && (
        <div className="flex flex-col gap-3">
          {data.map((l) => (
            <div key={l.id} className="card p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-[16px] font-semibold text-text-primary">
                    {l.name}
                  </h3>
                  <p className="mt-0.5 truncate text-[13px] text-text-secondary">
                    {SOURCE_LABEL[l.source_kind]}
                    {l.chat_ref ? ` · ${l.chat_ref}` : ""}
                  </p>
                  <p className="mt-0.5 text-[12px] text-text-tertiary">
                    Обновлено {timeAgo(l.parsed_at ?? l.created_at)}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[20px] font-bold tabular-nums text-text-primary">
                    {l.after_filters_count}
                  </div>
                  <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                    целей
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
