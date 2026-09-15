import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { useLimit } from "../../shared/limits";
import { Select } from "../../shared/Select";
import { haptic } from "../../shared/tg";
import { commentingApi } from "./api";
import { AccountPickRow } from "./components/AccountPickRow";
import {
  CapsuleButton,
  Field,
  RangeField,
  Section,
  SegmentedControl,
  TextArea,
  TextInput,
} from "./components/ui";
import type { LLMProvider } from "./types";

const TZ_OPTIONS = [
  "UTC",
  "Europe/Kiev",
  "Europe/Moscow",
  "Europe/Warsaw",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Europe/Madrid",
  "Europe/Istanbul",
  "Europe/Minsk",
  "Asia/Almaty",
  "Asia/Tbilisi",
  "Asia/Yerevan",
  "Asia/Dubai",
  "Asia/Tashkent",
  "Asia/Bangkok",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "America/Sao_Paulo",
];
const LLM_OPTIONS: { value: LLMProvider; label: string }[] = [
  { value: "deepseek", label: "DeepSeek" },
  { value: "gemini", label: "Gemini" },
];

export function NewCampaignScreen() {
  const navigate = useNavigate();
  const limit = useLimit("campaigns_active_max");
  useEffect(() => {
    if (limit?.atLimit) navigate("/billing", { replace: true });
  }, [limit?.atLimit, navigate]);
  const [name, setName] = useState("");
  const [llm, setLlm] = useState<LLMProvider>("deepseek");
  const [prompt, setPrompt] = useState("");
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("23:00");
  const [tz, setTz] = useState("Europe/Kiev");
  const [delayMin, setDelayMin] = useState(30);
  const [delayMax, setDelayMax] = useState(120);
  const [personaId, setPersonaId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const pool = useQuery({ queryKey: ["accounts", "pool"], queryFn: () => accountsApi.list("pool") });
  const personas = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });

  const valid = name.trim() !== "" && prompt.trim() !== "" && delayMin <= delayMax;

  const create = useMutation({
    mutationFn: async () => {
      const camp = await commentingApi.create({
        name: name.trim(),
        base_system_prompt: prompt.trim(),
        persona_id: personaId,
        llm_provider: llm,
        active_hours_start: `${start}:00`,
        active_hours_end: `${end}:00`,
        active_hours_tz: tz,
        posting_delay_min_sec: delayMin,
        posting_delay_max_sec: delayMax,
        enabled: true,
      });
      for (const id of selected) await commentingApi.attach(camp.id, id);
      return camp;
    },
    onSuccess: (camp) => {
      haptic("light");
      navigate(`/modules/commenting/campaigns/${camp.id}`);
    },
  });

  const setDelayMinClamped = (v: number) => {
    setDelayMin(v);
    if (v > delayMax) setDelayMax(v);
  };

  return (
    <div className="flex min-h-full flex-col pb-28 pt-1">
      <button
        onClick={() => navigate("/tasks")}
        className="mb-4 inline-flex w-fit items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Кампании
      </button>
      <h1 className="screen-title mb-6">Новая кампания</h1>

      <Section title="Основное">
        <Field label="Название">
          <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="Промо-кампания" />
        </Field>
        <p className="px-1 text-[12px] text-text-tertiary">
          Кампания — это папка для группы аккаунтов с общим промптом. Каналы для
          мониторинга задаются на каждом аккаунте отдельно.
        </p>
      </Section>

      <Section title="Модель">
        <SegmentedControl options={LLM_OPTIONS} value={llm} onChange={setLlm} />
      </Section>

      <Section title="Персона (необязательно)">
        <Select
          value={personaId != null ? String(personaId) : ""}
          onChange={(v) => setPersonaId(v === "" ? null : Number(v))}
          placeholder="Без персоны (голый промпт)"
          options={[
            { value: "", label: "Без персоны (голый промпт)" },
            ...(personas.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
          ]}
        />
        <p className="mt-1.5 px-1 text-[12px] text-text-tertiary">
          Персона добавляется в промпт (имя + черты). Применяется к аккаунтам без
          собственной персоны — у аккаунта своя перекрывает.
        </p>
      </Section>

      <Section title="Промпт">
        <TextArea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Ты — активный участник обсуждений. Пиши короткие релевантные комментарии…"
        />
      </Section>

      <Section title="Окно активности">
        <div className="flex gap-2">
          <Field label="С">
            <TextInput type="time" value={start} onChange={(e) => setStart(e.target.value)} className="nums" />
          </Field>
          <Field label="До">
            <TextInput type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="nums" />
          </Field>
        </div>
        <Field label="Часовой пояс">
          <Select
            value={tz}
            onChange={setTz}
            options={TZ_OPTIONS.map((t) => ({ value: t, label: t }))}
          />
        </Field>
      </Section>

      <Section title="Задержки постинга">
        <RangeField label="Минимум" value={delayMin} min={5} max={600} onChange={setDelayMinClamped} />
        <RangeField label="Максимум" value={delayMax} min={5} max={600} onChange={setDelayMax} />
      </Section>

      <Section title="Аккаунты из пула">
        {pool.data && pool.data.length > 0 ? (
          <div className="flex flex-col gap-2">
            {pool.data.map((a) => (
              <AccountPickRow
                key={a.id}
                account={a}
                selected={selected.has(a.id)}
                onToggle={() =>
                  setSelected((s) => {
                    const n = new Set(s);
                    n.has(a.id) ? n.delete(a.id) : n.add(a.id);
                    return n;
                  })
                }
              />
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-text-tertiary">В пуле нет свободных аккаунтов.</p>
        )}
      </Section>

      {create.isError && (
        <p className="mb-3 text-[13px] text-status-critical">Не удалось создать кампанию.</p>
      )}

      <StickyBar>
        <CapsuleButton
          variant={valid ? "accent" : "secondary"}
          disabled={!valid || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Создаём…" : "Создать кампанию"}
        </CapsuleButton>
      </StickyBar>
    </div>
  );
}

function StickyBar({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-30 mx-auto max-w-[440px] border-t border-hairline bg-bg-base px-5 pt-3"
      style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
    >
      {children}
    </div>
  );
}
