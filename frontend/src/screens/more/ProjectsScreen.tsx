import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Trash2, Users, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../shared/accounts";
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
import { GroupMembersSheet } from "./components/GroupMembersSheet";
import { BackHeader } from "./PersonasScreen";

/* «Группы аккаунтов» (в API и БД — projects): пользовательские наборы
 * аккаунтов. Не эксклюзивны с кампаниями: аккаунт может быть в группе и
 * одновременно работать в кампании. У аккаунта одна группа.
 * Группы используются прогревом (знакомые аккаунты общаются друг с другом),
 * фильтром списка аккаунтов и быстрым добавлением в кампанию. */

export function ProjectsScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [conflict, setConflict] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Project | null>(null);
  const [membersOf, setMembersOf] = useState<Project | null>(null);

  const list = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });
  const accounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const countByGroup = new Map<number, number>();
  for (const a of accounts.data ?? []) {
    if (a.project_id != null) countByGroup.set(a.project_id, (countByGroup.get(a.project_id) ?? 0) + 1);
  }

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
        setConflict("Группа с таким названием уже существует");
      } else {
        setConflict(e instanceof Error ? e.message : "Не удалось создать группу");
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
      <BackHeader title="Группы аккаунтов" onBack={() => navigate("/more")} />
      <p className="-mt-3 mb-6 max-w-[640px] px-1 text-[13px] text-text-tertiary">
        Объединяйте аккаунты в группы: аккаунты одной группы «знакомы» и общаются
        между собой при прогреве, по группе можно фильтровать список и одной
        кнопкой добавить всю группу в кампанию.
      </p>

      <div className="lg:grid lg:grid-cols-[380px_1fr] lg:items-start lg:gap-8">
      <Section title="Новая группа">
        <div className="card p-4">
          <Field label="Название">
            <TextInput
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setConflict(null);
              }}
              placeholder="Например: Крипто-чаты"
              maxLength={64}
            />
          </Field>
          <Field label="Описание (необязательно)">
            <TextInput
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Для чего эта группа"
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
              <ProjectRow
                key={p.id}
                project={p}
                count={countByGroup.get(p.id) ?? 0}
                onMembers={() => setMembersOf(p)}
                onDelete={() => setToDelete(p)}
              />
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">
            Групп ещё нет. Создайте первую и добавьте в неё аккаунты.
          </p>
        )}
      </Section>
      </div>

      {membersOf && (
        <GroupMembersSheet
          group={membersOf}
          groups={list.data ?? []}
          onClose={() => setMembersOf(null)}
        />
      )}

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить группу?"
        message={
          toDelete
            ? `Группа «${toDelete.name}» будет удалена. Сами аккаунты останутся, просто без группы.`
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

function ProjectRow({
  project,
  count,
  onMembers,
  onDelete,
}: {
  project: Project;
  count: number;
  onMembers: () => void;
  onDelete: () => void;
}) {
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
        <p className="truncate text-[12px] text-text-tertiary">
          {accountsWord(count)}
          {project.description && ` · ${project.description}`}
        </p>
      </div>
      <button
        onClick={onMembers}
        className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] text-text-primary hover:opacity-80"
      >
        <Users className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Аккаунты
      </button>
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

function accountsWord(n: number): string {
  const m10 = n % 10, m100 = n % 100;
  const w = m10 === 1 && m100 !== 11 ? "аккаунт" : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? "аккаунта" : "аккаунтов";
  return n === 0 ? "Пусто" : `${n} ${w}`;
}
