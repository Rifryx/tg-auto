import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bookmark, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { useLimit } from "../../shared/limits";
import { Select } from "../../shared/Select";
import { haptic } from "../../shared/tg";
import { accountPresetsApi, commentingApi, delayPresetsApi } from "./api";
import { AccountPickRow } from "./components/AccountPickRow";
import { AiProtectionCard } from "./components/AiProtectionCard";
import {
  CapsuleButton,
  Field,
  RangeField,
  Section,
  SegmentedControl,
  TextArea,
  TextInput,
  Toggle,
} from "./components/ui";
import type {
  AccountPreset,
  ChannelSourceMode,
  DelayPreset,
  LLMProvider,
  OnNotSubscribedAction,
  PostScope,
  PostSelectionMode,
  WorkMode,
} from "./types";

function classifyChannelInput(raw: string): "username" | "invite" | "folder" {
  const low = raw.trim().toLowerCase();
  if (low.includes("t.me/addlist/") || low.includes("t.me/list/")) return "folder";
  if (low.includes("t.me/joinchat/") || low.includes("t.me/+") || low.startsWith("+"))
    return "invite";
  return "username";
}

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
  const [delayMin, setDelayMin] = useState(50);
  const [delayMax, setDelayMax] = useState(100);
  // Join-delay и floodwait настраиваются пресетом задержек (§ Этап 1); в UI
  // сюда пока не выведены отдельные слайдеры — управление через пресет.
  const [joinMin, setJoinMin] = useState(80);
  const [joinMax, setJoinMax] = useState(160);
  const [floodPause, setFloodPause] = useState(120);
  const [floodMax, setFloodMax] = useState(3);
  const [personaId, setPersonaId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // ── Режимы отбора и работы (§ Этап 2) ──────────────────────────────
  const [selectionMode, setSelectionMode] = useState<PostSelectionMode>("all");
  const [keywordsText, setKeywordsText] = useState(""); // строки через \n
  const [probability, setProbability] = useState(100);
  const [perAccountProbability, setPerAccountProbability] = useState<
    Record<number, number>
  >({});
  const [postScope, setPostScope] = useState<PostScope>("new");
  const [workMode, setWorkMode] = useState<WorkMode>("by_count");
  const [maxComments, setMaxComments] = useState<string>(""); // пусто = без лимита
  const [minWords, setMinWords] = useState<number>(0);
  const [windowAfterPost, setWindowAfterPost] = useState<number>(3600);
  const [pauseBetween, setPauseBetween] = useState<number>(60);

  // ── Целевые каналы (§ Этап 3) ─────────────────────────────────────
  const [channelSourceMode, setChannelSourceMode] =
    useState<ChannelSourceMode>("explicit_links");
  const [channelLinksText, setChannelLinksText] = useState("");
  const [onNotSubscribed, setOnNotSubscribed] =
    useState<OnNotSubscribedAction>("notify_only");

  // ── Стиль комментариев (§ Этап 4) ──────────────────────────────────
  const [useEmojis, setUseEmojis] = useState(true);
  const [useStickers, setUseStickers] = useState(false);
  const [attachImage, setAttachImage] = useState(false);
  const [writeAsChannel, setWriteAsChannel] = useState(false);
  const [verifyAfterPost, setVerifyAfterPost] = useState(false);
  const [verifyDelaySec, setVerifyDelaySec] = useState(300);

  const pool = useQuery({ queryKey: ["accounts", "pool"], queryFn: () => accountsApi.list("pool") });
  const personas = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });
  const delayPresets = useQuery({ queryKey: ["delay-presets"], queryFn: delayPresetsApi.list });
  const accountPresets = useQuery({
    queryKey: ["account-presets"],
    queryFn: accountPresetsApi.list,
  });

  const keywordsList = useMemo(
    () =>
      keywordsText
        .split(/[\n,|]/)
        .map((s) => s.trim())
        .filter(Boolean),
    [keywordsText],
  );
  const channelLinksList = useMemo(
    () =>
      channelLinksText
        .split(/\n+/)
        .map((s) => s.trim())
        .filter(Boolean),
    [channelLinksText],
  );

  const valid =
    name.trim() !== "" &&
    prompt.trim() !== "" &&
    delayMin <= delayMax &&
    (selectionMode !== "keywords" || keywordsList.length > 0);

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
        join_delay_min_sec: joinMin,
        join_delay_max_sec: joinMax,
        floodwait_pause_sec: floodPause,
        floodwait_quarantine_max: floodMax,
        post_selection_mode: selectionMode,
        keywords: selectionMode === "keywords" ? keywordsList : [],
        probability_percent: selectionMode === "probability" ? probability : 100,
        post_scope: postScope,
        work_mode: workMode,
        max_comments: maxComments.trim() ? Number(maxComments) : null,
        min_words: minWords,
        window_after_post_sec:
          workMode === "by_time_window" ? windowAfterPost : null,
        pause_between_sec: workMode === "by_time_window" ? pauseBetween : null,
        channel_source_mode: channelSourceMode,
        on_not_subscribed_action: onNotSubscribed,
        use_emojis: useEmojis,
        use_stickers: useStickers,
        attach_image: attachImage,
        write_as_channel: writeAsChannel,
        verify_after_post: verifyAfterPost,
        verify_delay_sec: verifyDelaySec,
        enabled: true,
      });
      if (
        channelSourceMode === "explicit_links" &&
        channelLinksList.length > 0
      ) {
        try {
          await commentingApi.addChannels(camp.id, channelLinksList);
        } catch {
          /* некритично: ссылки можно добавить позже в деталях кампании */
        }
      }
      for (const id of selected) {
        const override =
          selectionMode === "probability" ? perAccountProbability[id] ?? null : null;
        await commentingApi.attach(camp.id, id, {
          probability_override: override,
        });
      }
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

      <AiProtectionCard />

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

      <Section title="Промпт LLM">
        <TextArea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Ты — активный участник обсуждений. Пиши короткие релевантные комментарии…"
        />
        <p className="px-1 text-[12px] text-text-tertiary">
          Обязательное поле. Если выбрана персона выше — её описание
          подмешивается к промпту (LLM подстраивает стиль под персону).
        </p>
      </Section>

      <Section title="Стиль комментариев">
        <div className="flex flex-col gap-3">
          <ToggleRow
            label="Использовать эмодзи"
            hint="Если выключено — LLM просят обойтись без эмодзи, а strip'ом чистим safety-net'ом."
            checked={useEmojis}
            onChange={setUseEmojis}
          />
          <ToggleRow
            label="Комментировать стикерами"
            hint="Часть комментариев уходит стикером из пака аккаунта (runtime — E4.1)."
            checked={useStickers}
            onChange={setUseStickers}
          />
          <ToggleRow
            label="Картинка к комментарию"
            hint="Прикладывает медиа-ассет к тексту (runtime — E4.1)."
            checked={attachImage}
            onChange={setAttachImage}
          />
          <ToggleRow
            label="Писать от имени канала"
            hint="Аккаунт должен быть админом канала с правом post. Иначе флаг игнорируется (E4.1)."
            checked={writeAsChannel}
            onChange={setWriteAsChannel}
          />
          <ToggleRow
            label="Контроль удаления комментариев"
            hint={`Через ${verifyDelaySec}с тот же аккаунт проверит, что коммент виден в чате (runtime — E4.2).`}
            checked={verifyAfterPost}
            onChange={setVerifyAfterPost}
          />
          {verifyAfterPost && (
            <Field label="Задержка проверки (сек)">
              <TextInput
                inputMode="numeric"
                value={String(verifyDelaySec)}
                onChange={(e) =>
                  setVerifyDelaySec(Math.max(1, Number(e.target.value.replace(/\D/g, "") || "0")))
                }
                className="nums"
              />
            </Field>
          )}
        </div>
      </Section>

      <Section title="Режим комментирования">
        <SegmentedControl
          options={[
            { value: "all", label: "Все посты" },
            { value: "keywords", label: "По словам" },
            { value: "probability", label: "По вероятности" },
          ]}
          value={selectionMode}
          onChange={(v) => setSelectionMode(v as PostSelectionMode)}
        />
        {selectionMode === "keywords" && (
          <div className="mt-3">
            <Field
              label="Ключевые слова"
              hint={<span className="text-[11px] text-text-tertiary">одно в строке или через `|`</span>}
            >
              <TextArea
                value={keywordsText}
                onChange={(e) => setKeywordsText(e.target.value)}
                placeholder={"крипта\nчат\nсообщество"}
              />
            </Field>
            <p className="px-1 text-[12px] text-text-tertiary">
              Пост попадает в очередь, если содержит хотя бы одно слово
              (регистр не важен). Пусто → ни один пост не пройдёт.
            </p>
          </div>
        )}
        {selectionMode === "probability" && (
          <div className="mt-3">
            <RangeField
              label={`Вероятность комментирования: ${probability}%`}
              value={probability}
              min={0}
              max={100}
              unit="%"
              onChange={setProbability}
            />
            <p className="px-1 text-[12px] text-text-tertiary">
              Тумблер «Пер-аккаунтная вероятность» появится ниже в списке
              выбранных аккаунтов — можно задать разную вероятность на каждый.
            </p>
          </div>
        )}
      </Section>

      <Section title="Какие посты комментировать">
        <SegmentedControl
          options={[
            { value: "new", label: "Новые" },
            { value: "existing", label: "Существующие" },
            { value: "mixed", label: "Сначала существующие" },
          ]}
          value={postScope}
          onChange={(v) => setPostScope(v as PostScope)}
        />
        {postScope !== "new" && (
          <p className="mt-2 px-1 text-[12px] text-text-tertiary">
            Backfill по истории канала в работе — см. DEFERRED-FEATURES [E2.1].
            Пока эти режимы эквивалентны «Новые».
          </p>
        )}
      </Section>

      <Section title="Режим работы">
        <SegmentedControl
          options={[
            { value: "by_count", label: "По количеству" },
            { value: "by_time_window", label: "По времени после поста" },
          ]}
          value={workMode}
          onChange={(v) => setWorkMode(v as WorkMode)}
        />
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label="Макс. комментариев (пусто = без лимита)">
            <TextInput
              inputMode="numeric"
              value={maxComments}
              onChange={(e) => setMaxComments(e.target.value.replace(/\D/g, ""))}
              placeholder="100"
              className="nums"
            />
          </Field>
          <Field label="Минимум слов в комменте">
            <TextInput
              inputMode="numeric"
              value={String(minWords)}
              onChange={(e) => setMinWords(Number(e.target.value.replace(/\D/g, "") || "0"))}
              className="nums"
            />
          </Field>
        </div>
        {workMode === "by_time_window" && (
          <div className="mt-1 grid grid-cols-2 gap-3">
            <Field label="Окно после публикации (сек)">
              <TextInput
                inputMode="numeric"
                value={String(windowAfterPost)}
                onChange={(e) => setWindowAfterPost(Number(e.target.value.replace(/\D/g, "") || "0"))}
                className="nums"
              />
            </Field>
            <Field label="Пауза между комментами (сек)">
              <TextInput
                inputMode="numeric"
                value={String(pauseBetween)}
                onChange={(e) => setPauseBetween(Number(e.target.value.replace(/\D/g, "") || "0"))}
                className="nums"
              />
            </Field>
          </div>
        )}
        <p className="px-1 text-[12px] text-text-tertiary">
          Лимиты применяются рантаймом — см. DEFERRED-FEATURES [E2.2]. Значения
          сохраняются в кампании и активируются, когда фича доедет.
        </p>
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
        <DelayPresetBar
          presets={delayPresets.data ?? []}
          onApply={(p) => {
            setDelayMin(p.posting_delay_min_sec);
            setDelayMax(p.posting_delay_max_sec);
            setJoinMin(p.join_delay_min_sec);
            setJoinMax(p.join_delay_max_sec);
            setFloodPause(p.floodwait_pause_sec);
            setFloodMax(p.floodwait_quarantine_max);
          }}
          currentValues={{
            posting_delay_min_sec: delayMin,
            posting_delay_max_sec: delayMax,
            join_delay_min_sec: joinMin,
            join_delay_max_sec: joinMax,
            floodwait_pause_sec: floodPause,
            floodwait_quarantine_max: floodMax,
          }}
        />
        <RangeField label="Минимум" value={delayMin} min={5} max={600} onChange={setDelayMinClamped} />
        <RangeField label="Максимум" value={delayMax} min={5} max={600} onChange={setDelayMax} />
        <p className="mt-1 px-1 text-[12px] text-text-tertiary">
          Пресет также задаёт задержки входа в канал ({joinMin}–{joinMax}s) и
          floodwait-паузу ({floodPause}s / карантин после {floodMax}).
        </p>
      </Section>

      <Section title="Целевые каналы">
        <SegmentedControl
          options={[
            { value: "explicit_links", label: "Юзернейм/Ссылка" },
            { value: "by_account_subscriptions", label: "По подпискам аккаунта" },
          ]}
          value={channelSourceMode}
          onChange={(v) => setChannelSourceMode(v as ChannelSourceMode)}
        />
        {channelSourceMode === "explicit_links" ? (
          <div className="mt-3">
            <Field
              label="Ссылки на каналы"
              hint={<span className="text-[11px] text-text-tertiary">по одной на строку</span>}
            >
              <TextArea
                value={channelLinksText}
                onChange={(e) => setChannelLinksText(e.target.value)}
                placeholder={"@username или https://t.me/channel_name\nt.me/joinchat/xxx"}
              />
            </Field>
            {channelLinksList.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {channelLinksList.map((raw) => {
                  const kind = classifyChannelInput(raw);
                  return (
                    <span
                      key={raw}
                      className={`rounded-pill border border-hairline bg-surface-1 px-2.5 py-0.5 text-[11px] ${
                        kind === "folder" ? "text-status-warning" : "text-text-secondary"
                      }`}
                    >
                      {raw} · {kind === "folder" ? "папка (скоро)" : kind}
                    </span>
                  );
                })}
              </div>
            )}
            <p className="mt-2 px-1 text-[12px] text-text-tertiary">
              Папки (`t.me/addlist/…`) сохраняются, но пока не резолвятся —
              см. DEFERRED-FEATURES [E3.1].
            </p>
          </div>
        ) : (
          <p className="mt-2 px-1 text-[12px] text-text-tertiary">
            Каждый аккаунт комментирует только каналы, на которые он подписан.
            Убедитесь, что у аккаунтов настроены `Мониторинг` — иначе очередь
            будет пустой.
          </p>
        )}
        <div className="mt-4">
          <Field label="Если аккаунт не подписан">
            <SegmentedControl
              options={[
                { value: "notify_only", label: "Только уведомить" },
                { value: "subscribe_and_notify", label: "Подписаться + уведомить" },
              ]}
              value={onNotSubscribed}
              onChange={(v) => setOnNotSubscribed(v as OnNotSubscribedAction)}
            />
          </Field>
          <p className="px-1 text-[12px] text-text-tertiary">
            Пуш-уведомления при обнаружении отсутствия подписки — через тот же
            канал, что и алерты по прокси. Runtime-обработчик — см.
            DEFERRED-FEATURES [E3.2].
          </p>
        </div>
      </Section>

      <Section title="Аккаунты из пула">
        <AccountPresetBar
          presets={accountPresets.data ?? []}
          selected={selected}
          onApply={(p) => setSelected(new Set(p.account_ids))}
          onSaved={() => {
            /* invalidate handled inside */
          }}
        />
        {pool.data && pool.data.length > 0 ? (
          <div className="mt-3 flex flex-col gap-2">
            {pool.data.map((a) => {
              const isSelected = selected.has(a.id);
              return (
                <div key={a.id}>
                  <AccountPickRow
                    account={a}
                    selected={isSelected}
                    onToggle={() =>
                      setSelected((s) => {
                        const n = new Set(s);
                        n.has(a.id) ? n.delete(a.id) : n.add(a.id);
                        return n;
                      })
                    }
                  />
                  {isSelected && selectionMode === "probability" && (
                    <div className="mt-1 rounded-chip border border-hairline bg-surface-1 px-3 py-2">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[12px] text-text-tertiary">
                          Своя вероятность
                        </span>
                        <button
                          onClick={() =>
                            setPerAccountProbability((m) => {
                              const n = { ...m };
                              if (a.id in n) delete n[a.id];
                              else n[a.id] = probability;
                              return n;
                            })
                          }
                          className={`rounded-pill px-2.5 py-0.5 text-[11px] font-semibold ${
                            a.id in perAccountProbability
                              ? "bg-accent text-accent-on"
                              : "bg-surface-2 text-text-secondary"
                          }`}
                        >
                          {a.id in perAccountProbability ? "вкл" : "выкл"}
                        </button>
                      </div>
                      {a.id in perAccountProbability && (
                        <RangeField
                          label={`${perAccountProbability[a.id]}%`}
                          value={perAccountProbability[a.id]}
                          min={0}
                          max={100}
                          unit="%"
                          onChange={(v) =>
                            setPerAccountProbability((m) => ({ ...m, [a.id]: v }))
                          }
                        />
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="mt-3 text-[13px] text-text-tertiary">В пуле нет свободных аккаунтов.</p>
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

/* Ряд с тумблером — label + подсказка слева, свитч справа. */
function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-chip border border-hairline bg-surface-1 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-[14px] text-text-primary">{label}</p>
        {hint && <p className="mt-0.5 text-[12px] text-text-tertiary">{hint}</p>}
      </div>
      <Toggle checked={checked} onChange={onChange} label={label} />
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

/* ── Пресеты задержек: чипы (системные + пользовательские) + «Сохранить свой».
   Системные (Мин / Рекомендуемые / Макс) сидятся миграцией 0027. */
type DelayValues = {
  posting_delay_min_sec: number;
  posting_delay_max_sec: number;
  join_delay_min_sec: number;
  join_delay_max_sec: number;
  floodwait_pause_sec: number;
  floodwait_quarantine_max: number;
};

function delayValuesEqual(a: DelayValues, b: DelayValues): boolean {
  return (
    a.posting_delay_min_sec === b.posting_delay_min_sec &&
    a.posting_delay_max_sec === b.posting_delay_max_sec &&
    a.join_delay_min_sec === b.join_delay_min_sec &&
    a.join_delay_max_sec === b.join_delay_max_sec &&
    a.floodwait_pause_sec === b.floodwait_pause_sec &&
    a.floodwait_quarantine_max === b.floodwait_quarantine_max
  );
}

function DelayPresetBar({
  presets,
  currentValues,
  onApply,
}: {
  presets: DelayPreset[];
  currentValues: DelayValues;
  onApply: (p: DelayPreset) => void;
}) {
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const activeId = useMemo(
    () => presets.find((p) => delayValuesEqual(p, currentValues))?.id ?? null,
    [presets, currentValues]
  );

  const create = useMutation({
    mutationFn: () =>
      delayPresetsApi.create({ name: name.trim(), ...currentValues }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["delay-presets"] });
      setSaving(false);
      setName("");
      haptic("light");
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => delayPresetsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["delay-presets"] }),
  });

  return (
    <div className="mb-3">
      <div className="flex flex-wrap gap-1.5">
        {presets.map((p) => {
          const active = p.id === activeId;
          return (
            <span
              key={p.id}
              className={`group inline-flex items-center gap-1 rounded-pill border px-3 py-1 text-[13px] transition-colors ${
                active
                  ? "border-strong bg-surface-2 text-text-primary"
                  : "border-hairline bg-surface-1 text-text-secondary active:text-text-primary"
              }`}
            >
              <button onClick={() => onApply(p)} className="font-medium">
                {p.name}
              </button>
              {!p.is_system && (
                <button
                  onClick={() => {
                    if (window.confirm(`Удалить пресет «${p.name}»?`)) remove.mutate(p.id);
                  }}
                  className="text-text-tertiary active:text-status-critical"
                  aria-label="Удалить пресет"
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
                </button>
              )}
            </span>
          );
        })}
        {!saving && (
          <button
            onClick={() => setSaving(true)}
            className="inline-flex items-center gap-1 rounded-pill border border-dashed border-hairline px-3 py-1 text-[13px] text-text-secondary active:text-text-primary"
          >
            <Bookmark className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
            Сохранить пресет
          </button>
        )}
      </div>
      {saving && (
        <div className="mt-3 flex items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название пресета"
            className="min-h-[40px] flex-1 rounded-chip border border-hairline bg-surface-1 px-3 text-[14px] text-text-primary outline-none focus:border-strong"
            autoFocus
          />
          <CapsuleButton
            variant="accent"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
            className="w-auto px-4"
          >
            {create.isPending ? "…" : "Сохранить"}
          </CapsuleButton>
          <CapsuleButton
            variant="secondary"
            onClick={() => { setSaving(false); setName(""); }}
            className="w-auto px-4"
          >
            Отмена
          </CapsuleButton>
        </div>
      )}
      {create.isError && (
        <p className="mt-2 px-1 text-[12px] text-status-critical">
          Не удалось сохранить пресет (возможно, имя занято).
        </p>
      )}
    </div>
  );
}

/* ── Пресеты аккаунтов: чипы (только пользовательские) + «Сохранить свой»
   из текущего выделения. Применение — заменяет выделение целиком. */
function AccountPresetBar({
  presets,
  selected,
  onApply,
}: {
  presets: AccountPreset[];
  selected: Set<number>;
  onApply: (p: AccountPreset) => void;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: () =>
      accountPresetsApi.create({
        name: name.trim(),
        account_ids: Array.from(selected),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-presets"] });
      setSaving(false);
      setName("");
      haptic("light");
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => accountPresetsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["account-presets"] }),
  });

  const canSave = selected.size > 0 && name.trim().length > 0 && !create.isPending;

  return (
    <div>
      {presets.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {presets.map((p) => (
            <span
              key={p.id}
              className="inline-flex items-center gap-1 rounded-pill border border-hairline bg-surface-1 px-3 py-1 text-[13px] text-text-secondary"
            >
              <button onClick={() => onApply(p)} className="font-medium active:text-text-primary">
                {p.name}
                <span className="ml-1.5 text-text-tertiary">({p.account_ids.length})</span>
              </button>
              <button
                onClick={() => {
                  if (window.confirm(`Удалить пресет «${p.name}»?`)) remove.mutate(p.id);
                }}
                className="text-text-tertiary active:text-status-critical"
                aria-label="Удалить пресет"
              >
                <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
              </button>
            </span>
          ))}
        </div>
      )}
      {!saving ? (
        <button
          onClick={() => setSaving(true)}
          disabled={selected.size === 0}
          className="inline-flex items-center gap-1 rounded-pill border border-dashed border-hairline px-3 py-1 text-[13px] text-text-secondary disabled:opacity-40 active:text-text-primary"
        >
          <Bookmark className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
          Сохранить как пресет ({selected.size})
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название пресета аккаунтов"
            className="min-h-[40px] flex-1 rounded-chip border border-hairline bg-surface-1 px-3 text-[14px] text-text-primary outline-none focus:border-strong"
            autoFocus
          />
          <CapsuleButton
            variant="accent"
            disabled={!canSave}
            onClick={() => create.mutate()}
            className="w-auto px-4"
          >
            {create.isPending ? "…" : "Сохранить"}
          </CapsuleButton>
          <CapsuleButton
            variant="secondary"
            onClick={() => { setSaving(false); setName(""); }}
            className="w-auto px-4"
          >
            Отмена
          </CapsuleButton>
        </div>
      )}
      {create.isError && (
        <p className="mt-2 px-1 text-[12px] text-status-critical">
          Не удалось сохранить пресет (возможно, имя занято).
        </p>
      )}
    </div>
  );
}
