import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PROFILE_LABEL } from "../../shared/status";
import type { WarmingProfile } from "../../shared/types";
import { Field, Section, SegmentedControl, TextInput } from "../../modules/commenting/components/ui";
import { BackHeader } from "./PersonasScreen";

/* Локальные значения по умолчанию (бэкенд-эндпоинта настроек нет — храним в
   localStorage как пресеты для форм). */
function useLocalSetting<T extends string>(key: string, fallback: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      return (localStorage.getItem(key) as T) || fallback;
    } catch {
      return fallback;
    }
  });
  const set = (val: T) => {
    setV(val);
    try {
      localStorage.setItem(key, val);
    } catch {
      /* приватный режим — игнорируем */
    }
  };
  return [v, set];
}

const PROFILE_OPTIONS: { value: WarmingProfile; label: string }[] = [
  { value: "minimal", label: PROFILE_LABEL.minimal },
  { value: "medium", label: PROFILE_LABEL.medium },
  { value: "dense", label: PROFILE_LABEL.dense },
];

export function SettingsScreen() {
  const navigate = useNavigate();
  const [profile, setProfile] = useLocalSetting<WarmingProfile>("default_profile", "medium");
  const [start, setStart] = useLocalSetting<string>("default_hours_start", "09:00");
  const [end, setEnd] = useLocalSetting<string>("default_hours_end", "23:00");

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Настройки" onBack={() => navigate("/more")} />

      <Section title="Прогрев по умолчанию">
        <div className="card p-4">
          <SegmentedControl options={PROFILE_OPTIONS} value={profile} onChange={setProfile} />
        </div>
      </Section>

      <Section title="Окно активности по умолчанию">
        <div className="card flex gap-2 p-4">
          <Field label="С">
            <TextInput type="time" value={start} onChange={(e) => setStart(e.target.value)} className="nums" />
          </Field>
          <Field label="До">
            <TextInput type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="nums" />
          </Field>
        </div>
      </Section>

      <Section title="LLM-ключи">
        <div className="card px-4">
          <KeyRow name="DeepSeek" />
          <div className="border-t border-hairline">
            <KeyRow name="Gemini" />
          </div>
        </div>
        <p className="mt-2 px-1 text-[12px] text-text-tertiary">
          Ключи хранятся на сервере и не отображаются. Статус доступности появится,
          когда бэкенд отдаст его через API.
        </p>
      </Section>
    </div>
  );
}

/* Статус ключа: пер-ключевого эндпоинта нет — показываем нейтрально, без утечки. */
function KeyRow({ name }: { name: string }) {
  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-[15px] text-text-primary">{name}</span>
      <span className="flex items-center gap-1.5 text-[13px] text-text-tertiary">
        <span className="h-2 w-2 rounded-full bg-status-neutral" aria-hidden />
        неизвестно
      </span>
    </div>
  );
}
