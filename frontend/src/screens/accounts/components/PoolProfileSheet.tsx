import { useState } from "react";
import { Field, TextInput, Toggle } from "../../../modules/commenting/components/ui";
import { CapsuleButton } from "./ui";

/* Конфигуратор bulk-действия apply_profile_pool (этап 3).
 *
 * Пользователь выбирает, какие поля распределить из пула оформления, и
 * опциональный тег-фильтр (общий для выбранных полей). Собирает payload:
 * включённое поле → tags (или [] = любые), выключенное → ключ опущен (None,
 * т.е. «не менять»). */
export function PoolProfileSheet({
  count,
  busy,
  onApply,
  onCancel,
}: {
  count: number;
  busy: boolean;
  onApply: (payload: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [firstName, setFirstName] = useState(true);
  const [lastName, setLastName] = useState(false);
  const [bio, setBio] = useState(true);
  const [avatar, setAvatar] = useState(true);
  const [username, setUsername] = useState(false);
  const [tags, setTags] = useState("");

  const anyField = firstName || lastName || bio || avatar || username;

  const build = (): Record<string, unknown> => {
    const t = tags.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
    const p: Record<string, unknown> = {};
    if (firstName) p.first_name_tags = t;
    if (lastName) p.last_name_tags = t;
    if (bio) p.bio_tags = t;
    if (avatar) p.avatar_tags = t;
    if (username) {
      p.username_from_pool = true;
      p.username_tags = t;
    }
    return p;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center px-4 pb-8 lg:items-center lg:pb-0 bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[420px] rounded-card border border-strong bg-bg-elevated p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[18px] font-semibold text-text-primary">Профиль из пула</h3>
        <p className="mt-1.5 text-[13px] text-text-secondary">
          Распределить случайные ассеты из пула на {count} акк. Выключенные поля
          не меняются.
        </p>

        <div className="mt-4 overflow-hidden rounded-card border border-hairline">
          <ToggleRow label="Имя" checked={firstName} onChange={setFirstName} />
          <ToggleRow label="Фамилия" checked={lastName} onChange={setLastName} />
          <ToggleRow label="О себе (BIO)" checked={bio} onChange={setBio} />
          <ToggleRow label="Аватар" checked={avatar} onChange={setAvatar} />
          <ToggleRow label="Username (из шаблонов)" checked={username} onChange={setUsername} last />
        </div>

        <div className="mt-4">
          <Field label="Тег-фильтр (опц.)">
            <TextInput
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="напр. ru — пусто = любые"
            />
          </Field>
        </div>

        <div className="mt-4 flex flex-col gap-2">
          <CapsuleButton
            variant={anyField ? "accent" : "secondary"}
            disabled={!anyField || busy}
            onClick={() => onApply(build())}
          >
            {busy ? "Применяем…" : "Применить"}
          </CapsuleButton>
          <CapsuleButton variant="secondary" onClick={onCancel} disabled={busy}>
            Отмена
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
  last,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  last?: boolean;
}) {
  return (
    <label
      className={`flex items-center justify-between px-4 py-3 ${last ? "" : "border-b border-hairline"}`}
    >
      <span className="text-[14px] text-text-secondary">{label}</span>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </label>
  );
}
