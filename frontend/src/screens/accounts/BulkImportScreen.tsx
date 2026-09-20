import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UploadCloud } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../shared/accounts";
import {
  CapsuleButton,
  Field,
  Section,
} from "../../modules/commenting/components/ui";
import { BackHeader } from "../more/PersonasScreen";

/* Массовый импорт (этап 1, UI).
 *
 * Два файла: ZIP с .session-файлами (имя каждого = телефон) и CSV с
 * мапой phone→proxy_id и опциональными полями. Импорт best-effort: показываем
 * отчёт по строкам. */

const CSV_HELP =
  "CSV: заголовок обязателен, минимум phone,proxy_id. " +
  "Опционально: warming_profile,persona_id,project_id,role,tags (tags через |).";

export function BulkImportScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [archive, setArchive] = useState<File | null>(null);
  const [mapping, setMapping] = useState<File | null>(null);

  const submit = useMutation({
    mutationFn: () => accountsApi.bulkImport(archive!, mapping!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const canSubmit = archive != null && mapping != null && !submit.isPending;

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Массовый импорт" onBack={() => navigate("/accounts")} />

      <Section title="Файлы">
        <div className="card p-4">
          <Field label="ZIP-архив с .session-файлами">
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => setArchive(e.target.files?.[0] ?? null)}
              className="block w-full text-[13px] text-text-secondary file:mr-3 file:rounded-pill file:border-0 file:bg-surface-2 file:px-4 file:py-2 file:text-[13px] file:text-text-primary"
            />
          </Field>
          <Field label="CSV с мапой phone → proxy_id" hint={<span className="text-[11px] text-text-tertiary">{CSV_HELP}</span>}>
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
      </Section>

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
    </div>
  );
}
