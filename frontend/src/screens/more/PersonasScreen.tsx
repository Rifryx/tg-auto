import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Persona } from "../../shared/types";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  Section,
  TextInput,
} from "../../modules/commenting/components/ui";
import { personasApi } from "./api";

export function PersonasScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [toDelete, setToDelete] = useState<Persona | null>(null);

  const list = useQuery({ queryKey: ["personas"], queryFn: personasApi.list });

  const create = useMutation({
    mutationFn: () =>
      personasApi.create({
        name: name.trim(),
        personality_tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      setName("");
      setTags("");
      qc.invalidateQueries({ queryKey: ["personas"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => personasApi.remove(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["personas"] });
    },
  });

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Персоны" onBack={() => navigate("/more")} />

      <Section title="Новая персона">
        <div className="card p-4">
          <Field label="Имя">
            <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="Алекс" />
          </Field>
          <Field label="Теги (через запятую)">
            <TextInput
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="дружелюбный, ироничный"
            />
          </Field>
          <CapsuleButton
            variant={name.trim() ? "accent" : "secondary"}
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Добавляем…" : "Добавить"}
          </CapsuleButton>
        </div>
      </Section>

      <Section title={`Все (${list.data?.length ?? 0})`}>
        {list.data && list.data.length > 0 ? (
          <div className="flex flex-col gap-2">
            {list.data.map((p) => (
              <div key={p.id} className="card flex items-center gap-3 px-4 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-[14px] font-semibold text-text-secondary">
                  {p.name.slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] text-text-primary">{p.name}</p>
                  <p className="truncate text-[12px] text-text-tertiary">
                    {p.personality_tags.join(" · ") || "без тегов"}
                  </p>
                </div>
                <button
                  onClick={() => setToDelete(p)}
                  aria-label="Удалить"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">Персон пока нет.</p>
        )}
      </Section>

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить персону?"
        message={`«${toDelete?.name}» будет удалена. Аккаунты без персоны продолжат работать.`}
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

export function BackHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <>
      <button
        onClick={onBack}
        className="mb-3 inline-flex items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Ещё
      </button>
      <h1 className="screen-title mb-6">{title}</h1>
    </>
  );
}
