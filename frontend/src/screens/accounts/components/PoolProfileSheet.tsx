import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Field, TextInput, Toggle } from "../../../modules/commenting/components/ui";
import { profileAssetsApi } from "../../more/api";
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
  // Пул оформления поддерживает только avatar и bio (имя/фамилия/username
  // из пула больше не заводятся — их в «Пул оформления» не добавить, см.
  // ProfileAssetsScreen.KINDS). Тумблеры для них убраны как неактуальные;
  // для случайных имён есть «Профиль ИИ».
  const [bio, setBio] = useState(true);
  const [avatar, setAvatar] = useState(true);
  const [tags, setTags] = useState("");

  // Загружаем пул, чтобы понять, какие виды ассетов вообще есть, и не
  // позволить запустить джобу, которая возьмёт мусор из пустого пула (баг,
  // на который жаловались: «Применить» запускалась даже при пустом пуле).
  const assets = useQuery({
    queryKey: ["profile-assets"],
    queryFn: () => profileAssetsApi.list(),
  });
  const pool = useMemo(() => {
    const items = assets.data ?? [];
    return {
      bio: items.filter((a) => a.kind === "bio").length,
      avatar: items.filter((a) => a.kind === "avatar").length,
    };
  }, [assets.data]);

  // Поле включено, но его в пуле нет → джобу запускать нельзя (нечему
  // применяться). Эти поля подсвечиваем предупреждением и блокируем кнопку.
  const missing: string[] = [];
  if (bio && pool.bio === 0) missing.push("BIO");
  if (avatar && pool.avatar === 0) missing.push("Аватар");

  const anyField = bio || avatar;
  const canApply = anyField && missing.length === 0 && !assets.isLoading;

  const build = (): Record<string, unknown> => {
    const t = tags.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
    const p: Record<string, unknown> = {};
    if (bio) p.bio_tags = t;
    if (avatar) p.avatar_tags = t;
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
          <ToggleRow label="О себе (BIO)" checked={bio} onChange={setBio} count={pool.bio} />
          <ToggleRow label="Аватар" checked={avatar} onChange={setAvatar} count={pool.avatar} last />
        </div>

        {missing.length > 0 && (
          <div className="mt-3 flex items-start gap-2 rounded-chip border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-[12px] text-status-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
            <div className="min-w-0 flex-1">
              <p>
                В пуле нет: <b>{missing.join(", ")}</b>. Выключите эти поля или{" "}
                <Link to="/more/profile-assets" className="underline" onClick={onCancel}>
                  добавьте ассеты в «Пул оформления»
                </Link>
                .
              </p>
            </div>
          </div>
        )}

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
            variant={canApply ? "accent" : "secondary"}
            disabled={!canApply || busy}
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
  count,
  last,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  count?: number;
  last?: boolean;
}) {
  const empty = count === 0;
  return (
    <label
      className={`flex items-center justify-between px-4 py-3 ${last ? "" : "border-b border-hairline"}`}
    >
      <span className="flex items-baseline gap-2">
        <span className="text-[14px] text-text-secondary">{label}</span>
        {count != null && (
          <span
            className={`text-[11px] ${empty ? "text-status-warning" : "text-text-tertiary"}`}
          >
            {empty ? "пусто" : `${count} в пуле`}
          </span>
        )}
      </span>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </label>
  );
}
