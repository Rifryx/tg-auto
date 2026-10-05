import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { parsingApi } from "./api";
import type { ListOp } from "./types";

/* Операции над списками (Extraction+, этап 1): пересечение / объединение /
   вычитание / сэмпл. Чисто DB — результат сразу появляется в списках. */

const OPS: { value: ListOp; label: string; hint: string }[] = [
  { value: "intersect", label: "Пересечение", hint: "Кто есть сразу в выбранных списках" },
  { value: "union", label: "Объединение", hint: "Все уникальные из выбранных" },
  { value: "subtract", label: "Вычитание", hint: "Из первого убрать всех из остальных" },
  { value: "sample", label: "Сэмпл", hint: "Случайная выборка из объединения" },
];

export function ListOpsScreen() {
  const navigate = useNavigate();
  const lists = useQuery({ queryKey: ["parsing", "lists"], queryFn: parsingApi.list });

  const [name, setName] = useState("");
  const [op, setOp] = useState<ListOp>("intersect");
  const [selected, setSelected] = useState<number[]>([]);
  const [minOverlap, setMinOverlap] = useState("");
  const [sampleSize, setSampleSize] = useState("100");

  const toggle = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const submit = useMutation({
    mutationFn: () =>
      parsingApi.listOps({
        name: name.trim(),
        op,
        source_list_ids: selected,
        min_overlap: op === "intersect" && minOverlap ? Number(minOverlap) : null,
        sample_size: op === "sample" ? Number(sampleSize) : null,
      }),
    onSuccess: () => navigate("/modules/parsing"),
  });

  const problems: string[] = [];
  if (!name.trim()) problems.push("Укажите имя списка");
  if (selected.length < 2) problems.push("Выберите минимум 2 списка");
  if (op === "sample" && !(Number(sampleSize) >= 1)) problems.push("Укажите размер сэмпла");

  const rows = lists.data ?? [];

  return (
    <div className="min-h-full">
      <ScreenHeader
        title="Операции над списками"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/parsing")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К спискам
          </button>
        }
      />

      <div className="flex flex-col gap-4">
        <div className="card p-5">
          <label className="block text-[13px] font-medium text-text-secondary">Имя нового списка</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Пересечение · крипто-чаты"
            className="mt-2 w-full rounded-xl border border-hairline bg-surface-2 p-3 text-[15px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
          />
        </div>

        <div className="card p-5">
          <div className="mb-3 text-[13px] font-medium uppercase tracking-wider text-text-secondary">Операция</div>
          <div className="grid grid-cols-2 gap-2">
            {OPS.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => setOp(o.value)}
                className={[
                  "rounded-xl border p-3 text-left transition-colors",
                  op === o.value ? "border-strong bg-surface-2" : "border-hairline bg-surface-1",
                ].join(" ")}
              >
                <div className="text-[14px] font-medium text-text-primary">{o.label}</div>
                <div className="mt-0.5 text-[12px] text-text-tertiary">{o.hint}</div>
              </button>
            ))}
          </div>

          {op === "intersect" && (
            <label className="mt-4 block text-[13px] font-medium text-text-secondary">
              Мин. вхождений (по умолчанию — во всех)
              <input
                type="number" min={2} value={minOverlap}
                onChange={(e) => setMinOverlap(e.target.value.replace(/\D/g, ""))}
                placeholder={String(Math.max(2, selected.length))}
                className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary"
              />
            </label>
          )}
          {op === "sample" && (
            <label className="mt-4 block text-[13px] font-medium text-text-secondary">
              Размер выборки
              <input
                type="number" min={1} value={sampleSize}
                onChange={(e) => setSampleSize(e.target.value.replace(/\D/g, ""))}
                className="mt-1 w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[15px] tabular-nums text-text-primary"
              />
            </label>
          )}
          {op === "subtract" && (
            <p className="mt-3 text-[12px] text-text-tertiary">
              Порядок важен: из <b>первого выбранного</b> вычитаются все остальные.
            </p>
          )}
        </div>

        <div className="card p-5">
          <div className="mb-3 text-[13px] font-medium uppercase tracking-wider text-text-secondary">
            Списки ({selected.length})
          </div>
          <div className="flex flex-col gap-1.5">
            {rows.map((l) => {
              const i = selected.indexOf(l.id);
              const on = i >= 0;
              return (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => toggle(l.id)}
                  className={[
                    "flex items-center gap-3 rounded-xl border p-3 text-left transition-colors",
                    on ? "border-strong bg-surface-2" : "border-hairline bg-surface-1",
                  ].join(" ")}
                >
                  <span
                    className={[
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] border text-[11px] font-bold",
                      on ? "border-accent bg-accent text-accent-on" : "border-strong bg-surface-1 text-text-tertiary",
                    ].join(" ")}
                  >
                    {on ? (op === "subtract" ? i + 1 : <Check className="h-3.5 w-3.5" strokeWidth={2.5} />) : ""}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium text-text-primary">{l.name}</div>
                    <div className="truncate text-[12px] text-text-tertiary">{l.after_filters_count} целей</div>
                  </div>
                </button>
              );
            })}
            {rows.length === 0 && <p className="text-[13px] text-text-tertiary">Списков пока нет.</p>}
          </div>
        </div>

        <div
          className="sticky bottom-0 z-10 -mx-4 mt-2 border-t border-hairline bg-bg-elevated/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
        >
          {submit.isError && (
            <p className="mb-2 text-[13px] text-status-critical">Не удалось выполнить операцию.</p>
          )}
          {problems.length > 0 && (
            <ul className="mb-2 text-[13px] text-text-secondary">
              {problems.map((p, i) => <li key={i}>• {p}</li>)}
            </ul>
          )}
          <button
            type="button"
            disabled={problems.length > 0 || submit.isPending}
            onClick={() => submit.mutate()}
            className={[
              "inline-flex h-11 w-full items-center justify-center gap-2 rounded-pill text-[15px] font-semibold transition-opacity",
              problems.length === 0 ? "bg-accent text-accent-on active:opacity-80" : "bg-surface-2 text-text-tertiary",
            ].join(" ")}
          >
            {submit.isPending ? "Выполняем…" : (<><Play className="h-4 w-4" strokeWidth={2.4} aria-hidden />Создать список</>)}
          </button>
        </div>
      </div>
    </div>
  );
}
