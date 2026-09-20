import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2, X, Check } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../shared/api";
import { projectsApi } from "../../shared/projects";
import type { Project } from "../../shared/types";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  Section,
  TextInput,
} from "../../modules/commenting/components/ui";
import { BackHeader } from "./PersonasScreen";

/* Экран проектов (этап 2, UI): CRUD пользовательских «папок».
 *
 * Проект — просто ярлык; не эксклюзивный, аккаунт можно назначить и в
 * проект, и в кампанию одновременно. Уникальность по (user_id, name). */

export function ProjectsScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [conflict, setConflict] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Project | null>(null);

  const list = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });

  const create = useMutation({
    mutationFn: () =>
      projectsApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
      }),
    onSuccess: () => {
      setName("");
      setDescription("");
      setConflict(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        setConflict("Проект с таким названием уже существует");
      } else {
        setConflict(e instanceof Error ? e.message : "Не удалось создать проект");
      }
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => projectsApi.remove(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Проекты" onBack={() => navigate("/more")} />

      <Section title="Новый проект">
        <div className="card p-4">
          <Field label="Название">
            <TextInput
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setConflict(null);
              }}
              placeholder="Клиент X"
              maxLength={64}
            />
          </Field>
          <Field label="Описание (необязательно)">
            <TextInput
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Летний запуск"
              maxLength={256}
            />
          </Field>
          {conflict && (
            <p className="mb-3 text-[12px] text-danger">{conflict}</p>
          )}
          <CapsuleButton
            variant={name.trim() ? "accent" : "secondary"}
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Создаём…" : "Создать"}
          </CapsuleButton>
        </div>
      </Section>

      <Section title={`Все (${list.data?.length ?? 0})`}>
        {list.data && list.data.length > 0 ? (
          <div className="flex flex-col gap-2">
            {list.data.map((p) => (
              <ProjectRow key={p.id} project={p} onDelete={() => setToDelete(p)} />
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">
            Проектов ещё нет. Создайте первый — так удобнее фильтровать аккаунты.
          </p>
        )}
      </Section>

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить проект?"
        message={
          toDelete
            ? `«${toDelete.name}» будет удалён. Аккаунты в проекте останутся, но потеряют привязку.`
            : ""
        }
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

function ProjectRow({ project, onDelete }: { project: Project; onDelete: () => void }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");

  const save = useMutation({
    mutationFn: () =>
      projectsApi.update(project.id, {
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  if (editing) {
    return (
      <div className="card flex flex-col gap-3 p-4">
        <Field label="Название">
          <TextInput value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
        </Field>
        <Field label="Описание">
          <TextInput
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={256}
          />
        </Field>
        <div className="flex gap-2">
          <CapsuleButton
            variant="secondary"
            onClick={() => {
              setEditing(false);
              setName(project.name);
              setDescription(project.description ?? "");
            }}
          >
            <span className="inline-flex items-center gap-1">
              <X className="h-4 w-4" strokeWidth={2} aria-hidden /> Отмена
            </span>
          </CapsuleButton>
          <CapsuleButton
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
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
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] text-text-primary">{project.name}</p>
        {project.description && (
          <p className="truncate text-[12px] text-text-tertiary">
            {project.description}
          </p>
        )}
      </div>
      <button
        onClick={() => setEditing(true)}
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
