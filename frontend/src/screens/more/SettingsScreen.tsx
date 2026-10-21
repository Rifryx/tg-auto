import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../shared/api";
import { PlanBadge } from "../../shared/PlanBadge";
import { PROFILE_LABEL } from "../../shared/status";
import { useCurrentPlan } from "../../shared/store";
import { hapticSelection } from "../../shared/tg";
import { showToast } from "../../shared/toast";
import type { WarmingProfile } from "../../shared/types";
import { Field, Section, SegmentedControl, TextInput } from "../../modules/commenting/components/ui";
import { useAppContent } from "./AboutScreen";
import { BackHeader } from "./PersonasScreen";

/* Набор частых IANA-таймзон для выпадающего списка. Определённую браузером TZ
   добавляем сверху, если её нет в списке. */
const TZ_OPTIONS = [
  "UTC",
  "Europe/Kaliningrad",
  "Europe/Moscow",
  "Europe/Kyiv",
  "Europe/Minsk",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Istanbul",
  "Asia/Yekaterinburg",
  "Asia/Almaty",
  "Asia/Novosibirsk",
  "Asia/Tashkent",
  "Asia/Dubai",
  "Asia/Tbilisi",
  "Asia/Yerevan",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
];

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

  const plan = useCurrentPlan();

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Настройки" onBack={() => navigate("/more")} />

      <Section title="Тариф">
        <button
          type="button"
          onClick={() => {
            hapticSelection();
            navigate("/billing");
          }}
          className="card flex w-full items-center gap-3 px-4 py-3.5 text-left active:bg-surface-2"
        >
          <PlanBadge size="md" />
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="text-[15px] font-semibold text-text-primary">
              {plan.id === "pro" ? "Pro активна" : "План Free"}
            </span>
            <span className="text-[12px] text-text-tertiary">
              {plan.id === "pro"
                ? "Весь функционал без ограничений"
                : "Перейти на Pro, чтобы снять лимиты"}
            </span>
          </div>
          <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
        </button>
      </Section>

      <Section title="Прогрев по умолчанию">
        <div className="card p-4">
          <SegmentedControl options={PROFILE_OPTIONS} value={profile} onChange={setProfile} />
        </div>
      </Section>

      <ActivityWindowSection />

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

/* Таймзона + окно активности. Хранятся на сервере (app_settings) и учитываются
   прогревом (фолбэк окна активности) и при отображении времён в UI. */
function ActivityWindowSection() {
  const qc = useQueryClient();
  const { data } = useAppContent();
  const [tz, setTz] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);

  const activity = data?.activity;
  const tzValue = tz ?? activity?.timezone ?? "UTC";
  const startValue = start ?? activity?.window_start ?? "09:00";
  const endValue = end ?? activity?.window_end ?? "23:00";

  const detected = (() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch {
      return "";
    }
  })();
  const options = Array.from(
    new Set([tzValue, detected, ...TZ_OPTIONS].filter(Boolean)),
  );

  const save = useMutation({
    mutationFn: () =>
      api.put("/app/settings/activity", {
        timezone: tzValue,
        window_start: startValue,
        window_end: endValue,
      }),
    onSuccess: () => {
      showToast("Сохранено", "success");
      qc.invalidateQueries({ queryKey: ["app", "content"] });
    },
    onError: () => showToast("Не удалось сохранить", "error"),
  });

  return (
    <Section title="Таймзона и окно активности">
      <div className="card flex flex-col gap-3 p-4">
        <Field label="Таймзона">
          <select
            value={tzValue}
            onChange={(e) => setTz(e.target.value)}
            className="w-full min-h-[48px] rounded-chip border border-hairline bg-surface-1 px-4 text-[16px] text-text-primary outline-none focus:border-strong"
          >
            {options.map((z) => (
              <option key={z} value={z}>
                {z}
                {z === detected ? " (ваша)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex gap-2">
          <Field label="С">
            <TextInput
              type="time"
              value={startValue}
              onChange={(e) => setStart(e.target.value)}
              className="nums"
            />
          </Field>
          <Field label="До">
            <TextInput
              type="time"
              value={endValue}
              onChange={(e) => setEnd(e.target.value)}
              className="nums"
            />
          </Field>
        </div>
        <p className="px-1 text-[12px] text-text-tertiary">
          Прогрев учитывает это окно в выбранной таймзоне, а времена в приложении
          показываются в ней же.
        </p>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate()}
          className="rounded-pill bg-accent px-4 py-3 text-[14px] font-semibold text-accent-on disabled:opacity-50"
        >
          {save.isPending ? "Сохраняем…" : "Сохранить"}
        </button>
      </div>
    </Section>
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
