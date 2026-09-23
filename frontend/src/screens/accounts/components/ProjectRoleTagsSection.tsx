import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { projectsApi, ROLE_OPTIONS } from "../../../shared/projects";
import { Select } from "../../../shared/Select";
import type { AccountRole } from "../../../shared/types";
import {
  Field,
  Section,
  TextInput,
} from "../../../modules/commenting/components/ui";
import { CapsuleButton } from "./ui";

/* Секция «Группа аккаунтов / роль / теги» на карточке аккаунта (в API —
 * project_id). Группа и роль — shared/Select, теги — строка через запятую.
 *
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
    <Section title="Группа и роль">
      <div className="card p-4">
        {/* Подписи — <p>, не <label>: у Select кнопка внутри. */}
        <div className="grid gap-x-3 sm:grid-cols-2 sm:items-end">
          <div className="mb-4">
            <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Группа аккаунтов</p>
            <Select
              value={localProject != null ? String(localProject) : ""}
              onChange={(v) => setLocalProject(v === "" ? null : Number(v))}
              options={[
                { value: "", label: "Без группы" },
                ...(projects.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
              ]}
            />
          </div>
          <div className="mb-4">
            <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Роль</p>
            <Select
              value={localRole ?? ""}
              onChange={(v) => setLocalRole((v || null) as AccountRole | null)}
              options={[{ value: "", label: "Без роли" }, ...ROLE_OPTIONS]}
            />
          </div>
        </div>
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
