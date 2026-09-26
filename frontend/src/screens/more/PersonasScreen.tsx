import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LimitBanner } from "../../shared/LimitBanner";
import { useLimit } from "../../shared/limits";
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

  const limit = useLimit("personas_max");
  const blocked = limit?.atLimit ?? false;

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Персоны" onBack={() => navigate("/more")} />

      <Section title="Новая персона">
        <LimitBanner feature="personas_max" />
        <div className="card p-4">
          <Field label="Имя">
            <TextInput
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Алекс"
              disabled={blocked}
            />
          </Field>
          <Field label="Теги (через запятую)">
            <TextInput
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="дружелюбный, ироничный"
              disabled={blocked}
            />
          </Field>
          <CapsuleButton
            variant={!blocked && name.trim() ? "accent" : "secondary"}
            disabled={blocked || !name.trim() || create.isPending}
            onClick={() => {
              if (blocked) return navigate("/billing");
              create.mutate();
            }}
          >
            {blocked ? "Лимит достигнут" : create.isPending ? "Добавляем…" : "Добавить"}
          </CapsuleButton>
        </div>
      </Section>

      <Section title={`Все (${list.data?.length ?? 0})`}>
        {list.data && list.data.length > 0 ? (
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-3">
            {list.data.map((p) => (
              <PersonaRow key={p.id} persona={p} onDelete={() => setToDelete(p)} />
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

/* Ряд персоны: просмотр + инлайн-редактирование имени и тегов. */
function PersonaRow({ persona, onDelete }: { persona: Persona; onDelete: () => void }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(persona.name);
  const [tags, setTags] = useState(persona.personality_tags.join(", "));

  const save = useMutation({
    mutationFn: () =>
      personasApi.update(persona.id, {
        name: name.trim(),
        personality_tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["personas"] });
    },
  });

  const startEdit = () => {
    setName(persona.name);
    setTags(persona.personality_tags.join(", "));
    setEditing(true);
  };

  if (editing) {
    return (
      <div className="card flex flex-col gap-3 p-4">
        <Field label="Имя">
          <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя" />
        </Field>
        <Field label="Теги (через запятую)">
          <TextInput value={tags} onChange={(e) => setTags(e.target.value)} placeholder="дружелюбный, ироничный" />
        </Field>
        <div className="flex gap-2">
          <CapsuleButton variant="secondary" onClick={() => setEditing(false)}>
            <span className="inline-flex items-center gap-1"><X className="h-4 w-4" strokeWidth={2} aria-hidden /> Отмена</span>
          </CapsuleButton>
          <CapsuleButton disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            <span className="inline-flex items-center gap-1">
              <Check className="h-4 w-4" strokeWidth={2} aria-hidden />
              {save.isPending ? "Сохраняем…" : "Сохранить"}
            </span>
          </CapsuleButton>
        </div>
      </div>
    );
  }

  return (
    <div className="card flex items-center gap-3 px-4 py-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-[14px] font-semibold text-text-secondary">
        {persona.name.slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] text-text-primary">{persona.name}</p>
        <p className="truncate text-[12px] text-text-tertiary">
          {persona.personality_tags.join(" · ") || "без тегов"}
        </p>
      </div>
      <button
        onClick={startEdit}
        aria-label="Изменить"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
      >
        <Pencil className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </button>
      <button
        onClick={onDelete}
        aria-label="Удалить"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical"
      >
        <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </button>
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
