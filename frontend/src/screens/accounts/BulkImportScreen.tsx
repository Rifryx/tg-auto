import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Inbox, UploadCloud } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../shared/accounts";
import { useLimit } from "../../shared/limits";
import {
  CapsuleButton,
  Field,
  Section,
} from "../../modules/commenting/components/ui";
import { BackHeader } from "../more/PersonasScreen";

/* Массовый импорт аккаунтов (§ Этап 0).
 *
 * UI по образцу конкурента: две крупные drop-зоны (TData и .session)
 * плюс счётчик занятого лимита сверху. TData — заглушка «скоро»
 * (см. docs/DEFERRED-FEATURES.md → [E0.2]).
 * CSV-путь для одиночной .session + mapping остаётся, но убран
 * в свёрнутый аккордеон — используется реже. */

const CSV_HELP =
  "CSV: заголовок обязателен, минимум phone,proxy_id. " +
  "Опционально: warming_profile,persona_id,project_id,role,tags (tags через |).";

export function BulkImportScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const limit = useLimit("accounts_max");

  const [archive, setArchive] = useState<File | null>(null);
  const [mapping, setMapping] = useState<File | null>(null);
  const [csvOpen, setCsvOpen] = useState(false);

  const submit = useMutation({
    mutationFn: () => accountsApi.bulkImport(archive!, mapping!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const canSubmit = archive != null && mapping != null && !submit.isPending;

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Импортировать аккаунты" onBack={() => navigate("/accounts")} />

      {limit && <LimitProgress used={limit.used} limit={limit.limit} />}

      <Section title="Источник">
        <div className="grid grid-cols-2 gap-3">
          <TDataDropZone />
          <SessionZipDropZone
            file={archive}
            onFile={setArchive}
          />
        </div>
        <p className="mt-3 px-1 text-center text-[12px] text-text-tertiary">
          Или перетащите файлы сюда
        </p>
      </Section>

      {/* Свёрнутая CSV-ветка: одиночная сессия + mapping — старый flow. */}
      <Section title="Дополнительно">
        <button
          onClick={() => setCsvOpen((v) => !v)}
          className="text-[14px] text-text-secondary active:text-text-primary"
        >
          {csvOpen ? "Скрыть CSV-импорт" : "CSV с mapping phone → proxy_id"}
        </button>
        {csvOpen && (
          <div className="mt-4">
            <Field
              label="CSV с мапой phone → proxy_id"
              hint={<span className="text-[11px] text-text-tertiary">{CSV_HELP}</span>}
            >
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setMapping(e.target.files?.[0] ?? null)}
                className="block w-full text-[13px] text-text-secondary file:mr-3 file:rounded-pill file:border-0 file:bg-surface-2 file:px-4 file:py-2 file:text-[13px] file:text-text-primary"
              />
            </Field>
            <CapsuleButton
              variant={canSubmit ? "accent" : "secondary"}
              disabled={!canSubmit}
              onClick={() => submit.mutate()}
            >
              <span className="inline-flex items-center gap-2">
                <UploadCloud className="h-4 w-4" strokeWidth={2} aria-hidden />
                {submit.isPending ? "Импортируем…" : "Импортировать"}
              </span>
            </CapsuleButton>
          </div>
        )}
      </Section>

      {archive && !csvOpen && !mapping && (
        <p className="mb-4 px-1 text-[12px] text-text-tertiary">
          ZIP выбран. Чтобы импортировать несколько .session, приложите mapping —
          раскройте «CSV с mapping». Одиночную .session загружайте через «Новый аккаунт».
        </p>
      )}

      {submit.isError && (
        <p className="mb-4 px-1 text-[13px] text-danger">
          {submit.error instanceof Error ? submit.error.message : "Ошибка импорта"}
        </p>
      )}

      {submit.data && (
        <>
          <Section title={`Импортировано: ${submit.data.totals.imported}`}>
            {submit.data.imported.length > 0 ? (
              <div className="card overflow-hidden p-0">
                {submit.data.imported.map((it, i) => (
                  <div
                    key={`${it.phone}-${i}`}
                    className={
                      "flex items-center justify-between px-4 py-2 " +
                      (i > 0 ? "border-t border-hairline" : "")
                    }
                  >
                    <span className="text-[14px] text-text-primary">{it.phone}</span>
                    <span className="text-[12px] text-text-tertiary">#{it.account_id}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="px-1 text-[13px] text-text-tertiary">Ничего.</p>
            )}
          </Section>

          <Section title={`Пропущено: ${submit.data.totals.skipped}`}>
            {submit.data.skipped.length > 0 ? (
              <div className="card overflow-hidden p-0">
                {submit.data.skipped.map((it, i) => (
                  <div
                    key={`${it.phone}-${i}`}
                    className={
                      "flex flex-col gap-0.5 px-4 py-2 " +
                      (i > 0 ? "border-t border-hairline" : "")
                    }
                  >
                    <span className="text-[14px] text-text-primary">{it.phone}</span>
                    <span className="truncate text-[12px] text-danger">{it.reason}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="px-1 text-[13px] text-text-tertiary">Ошибок нет.</p>
            )}
          </Section>
        </>
      )}

      {!submit.data && archive == null && (
        <EmptyState />
      )}
    </div>
  );
}

function LimitProgress({ used, limit }: { used: number; limit: number }) {
  const isUnlimited = limit < 0;
  const pct = isUnlimited || limit === 0 ? 0 : Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="mb-5 rounded-card border border-hairline bg-surface-1 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[13px] text-text-primary">
          Занято: <span className="font-semibold">{used}</span>
          {" / "}
          <span className="text-text-secondary">{isUnlimited ? "∞" : limit}</span>
          {" "}
          <span className="text-text-tertiary">
            {isUnlimited ? "" : `бесплатных`}
          </span>
        </span>
        <span className="text-[12px] text-text-tertiary">Откуда лимит</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full bg-accent transition-[width]"
          style={{ width: `${pct}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}

function TDataDropZone() {
  return (
    <div
      className="flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-hairline bg-surface-1 p-4 text-center"
      aria-disabled
    >
      <FolderOpen className="h-8 w-8 text-accent" strokeWidth={1.5} aria-hidden />
      <p className="text-[14px] font-semibold text-text-primary">TData</p>
      <p className="text-[11px] text-text-tertiary">папка или ZIP-архив</p>
      <span className="mt-1 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-text-tertiary">
        скоро
      </span>
    </div>
  );
}

function SessionZipDropZone({
  file,
  onFile,
}: {
  file: File | null;
  onFile: (f: File | null) => void;
}) {
  return (
    <label className="flex min-h-[160px] cursor-pointer flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-hairline bg-surface-1 p-4 text-center transition-colors active:border-strong">
      <UploadCloud className="h-8 w-8 text-accent" strokeWidth={1.5} aria-hidden />
      <p className="text-[14px] font-semibold text-text-primary">.session</p>
      <p className="text-[11px] text-text-tertiary">
        {file ? file.name : "ZIP с .session-файлами"}
      </p>
      <input
        type="file"
        accept=".zip,application/zip"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        className="hidden"
      />
    </label>
  );
}

function EmptyState() {
  return (
    <div className="mt-4 flex flex-col items-center gap-3 rounded-card border border-hairline bg-surface-1 px-6 py-12 text-center">
      <Inbox className="h-10 w-10 text-text-tertiary" strokeWidth={1.4} aria-hidden />
      <p className="text-[15px] font-semibold text-text-primary">Нет загруженных аккаунтов</p>
      <p className="max-w-[260px] text-[12px] text-text-tertiary">
        Загрузите TData или .session файлы, чтобы начать работу
      </p>
    </div>
  );
}
