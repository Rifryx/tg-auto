import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Trash2, Users, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi } from "../../shared/accounts";
import { ApiError } from "../../shared/api";
import { projectsApi } from "../../shared/projects";
import { AccountAvatar } from "../../shared/AccountAvatar";
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
  // Выбор аккаунтов прямо при создании группы.
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pickerOpen, setPickerOpen] = useState(false);

  const list = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });
  const accounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const countByGroup = new Map<number, number>();
  for (const a of accounts.data ?? []) {
    if (a.project_id != null) countByGroup.set(a.project_id, (countByGroup.get(a.project_id) ?? 0) + 1);
  }

  const togglePick = (id: number) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const create = useMutation({
    mutationFn: async () => {
      const project = await projectsApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      // Сразу привязываем выбранные аккаунты к новой группе.
      if (picked.size > 0) {
        await projectsApi.setAccounts(project.id, [...picked]);
      }
      return project;
    },
    onSuccess: () => {
      setName("");
      setDescription("");
      setPicked(new Set());
      setPickerOpen(false);
      setConflict(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
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

      {/* 2 колонки — только на действительно широком экране. На ноутбучных 1280-
          1366px после сайдбара (~250px) правой колонке не хватает места на форму
          редактирования группы (кнопка «Сохранить» обрезалась). Поэтому порог
          xl: (1280px), и даже тогда правой колонке даём минимум — а не 1fr без
          защиты от сжатия, чтобы кнопки форм помещались. */}
      <div className="xl:grid xl:grid-cols-[360px_minmax(0,1fr)] xl:items-start xl:gap-6">
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

          <Field label="Аккаунты (необязательно)">
            <button
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-left text-[15px] text-text-primary active:bg-surface-2"
            >
              <span className={picked.size ? "text-text-primary" : "text-text-tertiary"}>
                {picked.size ? `Выбрано: ${picked.size}` : "Выбрать аккаунты из списка"}
              </span>
              <span className="text-text-tertiary">{pickerOpen ? "▲" : "▼"}</span>
            </button>
            {pickerOpen && (
              <div className="mt-2 max-h-56 overflow-y-auto rounded-chip border border-hairline bg-surface-1 p-1.5">
                {(accounts.data ?? []).length === 0 ? (
                  <p className="px-2 py-2 text-[13px] text-text-tertiary">Нет аккаунтов.</p>
                ) : (
                  (accounts.data ?? []).map((a) => {
                    const checked = picked.has(a.id);
                    const inOther = a.project_id != null;
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => togglePick(a.id)}
                        className="flex w-full items-center gap-2.5 rounded-chip px-2.5 py-2 text-left active:bg-surface-2"
                      >
                        <span
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                            checked
                              ? "border-transparent bg-accent text-accent-on"
                              : "border-hairline bg-surface-2"
                          }`}
                        >
                          {checked && <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />}
                        </span>
                        <AccountAvatar
                          avatarUrl={a.avatar_url}
                          fallback={a.first_name || a.username || a.phone}
                        />
                        <span className="min-w-0 flex-1 truncate text-[14px] text-text-primary">
                          {a.username ? `@${a.username}` : a.phone}
                        </span>
                        {inOther && (
                          <span className="shrink-0 text-[11px] text-text-tertiary">в другой группе</span>
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            )}
            {picked.size > 0 && (
              <p className="mt-1 px-1 text-[11px] text-text-tertiary">
                Выбранные аккаунты будут перемещены в эту группу (у аккаунта одна группа).
              </p>
            )}
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
