import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Package, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { haptic } from "../../shared/tg";
import { productsApi, type Product, type ProductBody } from "./api";

/* База знаний «Продукты» нейрошиллинга.
   Один раз описал продукт — переиспользуешь во всех кампаниях (связывается
   через product_id в карточке кампании). LLM-рерайтинг при генерации реплик
   получает описание как контекст — не нужно дублировать brand_name/topic
   в каждой кампании. */
export function ShillingProductsScreen() {
  const qc = useQueryClient();
  const products = useQuery({
    queryKey: ["shilling", "products"],
    queryFn: productsApi.list,
  });
  const [editing, setEditing] = useState<Product | "new" | null>(null);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "products"] });

  const removeMut = useMutation({
    mutationFn: (id: number) => productsApi.remove(id),
    onSuccess: invalidate,
  });

  return (
    <div className="min-h-full pb-6">
      <ScreenHeader
        title="Продукты"
        action={
          <button
            onClick={() => {
              haptic();
              setEditing("new");
            }}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-4 text-[14px] font-medium text-accent-on active:opacity-80"
          >
            <Plus className="h-4 w-4" strokeWidth={2.2} aria-hidden />
            Новый
          </button>
        }
      />

      <p className="mb-4 max-w-[640px] text-[13px] text-text-secondary">
        Опишите продукт один раз (название, УТП, ссылка, подробное описание) —
        и привязывайте его к любым кампаниям нейрошиллинга. ИИ при рерайтинге
        реплик будет использовать это описание как контекст продвижения.
      </p>

      {products.isLoading && (
        <div className="text-[13px] text-text-tertiary">Загрузка…</div>
      )}

      {!products.isLoading && (products.data ?? []).length === 0 && (
        <div>
          <EmptyState
            icon={Package}
            title="Пока нет продуктов"
            hint="Добавьте первый — он сразу станет доступен для привязки к кампаниям."
          />
          <div className="mt-2 flex justify-center">
            <button
              onClick={() => setEditing("new")}
              className="rounded-pill bg-accent px-5 py-2 text-[14px] font-medium text-accent-on"
            >
              Добавить продукт
            </button>
          </div>
        </div>
      )}

      {(products.data ?? []).length > 0 && (
        <div className="flex flex-col gap-2">
          {(products.data ?? []).map((p) => (
            <div
              key={p.id}
              className="card flex items-start gap-3 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold text-text-primary">
                  {p.name}
                </p>
                {p.usp && (
                  <p className="truncate text-[13px] text-text-secondary">
                    {p.usp}
                  </p>
                )}
                {p.website && (
                  <a
                    href={p.website}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-[12px] text-text-tertiary hover:text-text-primary"
                  >
                    <Globe className="h-3 w-3" aria-hidden />
                    {p.website.replace(/^https?:\/\//, "")}
                  </a>
                )}
              </div>
              <button
                onClick={() => setEditing(p)}
                aria-label="Изменить"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
              >
                <Pencil className="h-4 w-4" strokeWidth={1.8} aria-hidden />
              </button>
              <button
                onClick={() => {
                  if (confirm(`Удалить продукт «${p.name}»?`))
                    removeMut.mutate(p.id);
                }}
                aria-label="Удалить"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical"
              >
                <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
              </button>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <ProductSheet
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            invalidate();
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function ProductSheet({
  initial,
  onClose,
  onSaved,
}: {
  initial: Product | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<ProductBody>({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    usp: initial?.usp ?? "",
    website: initial?.website ?? "",
    tags: initial?.tags ?? "",
  });

  const save = useMutation({
    mutationFn: () =>
      initial
        ? productsApi.update(initial.id, {
            ...form,
            // пустые строки превращаем в null — чтобы на бэке не хранить "".
            usp: form.usp?.trim() || null,
            website: form.website?.trim() || null,
            tags: form.tags?.trim() || null,
          })
        : productsApi.create({
            ...form,
            name: form.name.trim(),
            description: (form.description ?? "").trim(),
            usp: form.usp?.trim() || null,
            website: form.website?.trim() || null,
            tags: form.tags?.trim() || null,
          }),
    onSuccess: onSaved,
  });

  const canSave = form.name.trim().length > 0 && !save.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center lg:p-6">
      <div onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        className="relative mx-auto flex max-h-[92vh] w-full max-w-[560px] flex-col overflow-y-auto rounded-t-[28px] border border-hairline bg-bg-elevated p-5 pb-[calc(env(safe-area-inset-bottom)+16px)] lg:rounded-[28px] lg:pb-5"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-text-primary">
            {initial ? "Редактировать продукт" : "Новый продукт"}
          </h2>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <ProductField label="Название" required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Например, Нейрокомментинг"
            maxLength={200}
            className={INPUT}
          />
        </ProductField>

        <ProductField label="УТП (одной строкой)">
          <input
            value={form.usp ?? ""}
            onChange={(e) => setForm({ ...form, usp: e.target.value })}
            placeholder="Автокомментарии в Telegram с ИИ — много дешёвых заявок"
            maxLength={500}
            className={INPUT}
          />
        </ProductField>

        <ProductField label="Сайт / основная ссылка">
          <input
            value={form.website ?? ""}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
            placeholder="https://example.com"
            maxLength={500}
            className={INPUT}
          />
        </ProductField>

        <ProductField
          label="Описание"
          hint="Фичи, преимущества, кому подходит — всё, что ИИ должен знать при генерации реплик."
        >
          <textarea
            value={form.description ?? ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Что умеет, чем лучше альтернатив, для кого…"
            maxLength={10_000}
            rows={5}
            className={`${INPUT} resize-y py-3 leading-relaxed`}
          />
        </ProductField>

        <ProductField
          label="Теги (через запятую)"
          hint="Для будущего авто-подбора продукта под целевой чат."
        >
          <input
            value={form.tags ?? ""}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
            placeholder="telegram, маркетинг, ai"
            maxLength={500}
            className={INPUT}
          />
        </ProductField>

        {save.isError && (
          <p className="mb-2 text-[12px] text-status-critical">
            Не удалось сохранить. Проверьте поля и попробуйте снова.
          </p>
        )}

        <div className="mt-2 flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-pill border border-hairline bg-surface-2 px-4 py-3 text-[14px] font-medium text-text-primary active:opacity-80"
          >
            Отмена
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={!canSave}
            className="flex-1 rounded-pill bg-accent px-4 py-3 text-[14px] font-medium text-accent-on active:opacity-80 disabled:opacity-50"
          >
            {save.isPending ? "Сохраняем…" : initial ? "Сохранить" : "Создать"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ProductField({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-4 block">
      <span className="mb-1.5 flex items-center gap-1 px-1 text-[13px] text-text-tertiary">
        {label}
        {required && <span className="text-status-critical">*</span>}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block px-1 text-[11px] leading-relaxed text-text-tertiary">
          {hint}
        </span>
      )}
    </label>
  );
}

const INPUT =
  "w-full min-h-[44px] rounded-chip border border-hairline bg-surface-1 px-3.5 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong";
