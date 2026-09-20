import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { projectsApi, ROLE_OPTIONS } from "../../../shared/projects";
import type { AccountRole } from "../../../shared/types";
import {
  Field,
  Section,
  TextInput,
} from "../../../modules/commenting/components/ui";
import { CapsuleButton } from "./ui";

/* Секция «Проект / роль / теги» на карточке аккаунта (этап 2, UI).
 *
 * Три поля независимо: выбор проекта (dropdown), выбор роли (dropdown),
 * теги (комма-разделённая строка). Сохранение — по нажатию на «Сохранить»
 * или на blur каждого поля. Здесь по-минимуму: единая кнопка внизу секции. */

interface Props {
  accountId: number;
  projectId: number | null;
  role: AccountRole | null;
  tags: string[];
}

export function ProjectRoleTagsSection({
  accountId,
  projectId,
  role,
  tags,
}: Props) {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });

  const [localProject, setLocalProject] = useState<number | null>(projectId);
  const [localRole, setLocalRole] = useState<AccountRole | null>(role);
  const [localTags, setLocalTags] = useState<string>(tags.join(", "));

  const save = useMutation({
    mutationFn: () =>
      accountsApi.patch(accountId, {
        project_id: localProject,
        role: localRole,
        tags: localTags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account", accountId] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const dirty =
    localProject !== projectId ||
    localRole !== role ||
    localTags !==
      tags.join(", ");

  return (
    <Section title="Проект и роль">
      <div className="card p-4">
        <Field label="Проект">
          <select
            value={localProject ?? ""}
            onChange={(e) =>
              setLocalProject(e.target.value === "" ? null : Number(e.target.value))
            }
            className="w-full rounded-xl border border-hairline bg-surface-1 px-3 py-2 text-[15px] text-text-primary outline-none"
          >
            <option value="">Без проекта</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Роль">
          <select
            value={localRole ?? ""}
            onChange={(e) =>
              setLocalRole((e.target.value || null) as AccountRole | null)
            }
            className="w-full rounded-xl border border-hairline bg-surface-1 px-3 py-2 text-[15px] text-text-primary outline-none"
          >
            <option value="">—</option>
            {ROLE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Теги (через запятую)">
          <TextInput
            value={localTags}
            onChange={(e) => setLocalTags(e.target.value)}
            placeholder="vip, seo, зарубеж"
          />
        </Field>
        <CapsuleButton
          variant={dirty ? "accent" : "secondary"}
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Сохраняем…" : dirty ? "Сохранить" : "Без изменений"}
        </CapsuleButton>
      </div>
    </Section>
  );
}
