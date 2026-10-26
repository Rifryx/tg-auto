import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Bookmark, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { StickyActionBar } from "../../components/StickyActionBar";
import { ErrorBanner } from "../../components/ErrorBanner";
import { humanizeError } from "../../shared/api";
import { accountsApi, catalogApi } from "../../shared/accounts";
import { useLimit } from "../../shared/limits";
import { projectsApi } from "../../shared/projects";
import { accountWorkWarning, sortForWork } from "../../shared/status";
import { Select } from "../../shared/Select";
import { TimeField } from "../../shared/TimeField";
import { haptic } from "../../shared/tg";
import { commentingApi, delayPresetsApi } from "./api";
import { AccountPickRow } from "./components/AccountPickRow";
import { AddGroupBar } from "./components/AddGroupBar";
import { AiProtectionCard } from "./components/AiProtectionCard";
import { MediaPickerInline } from "./components/MediaPickerInline";
import {
  CapsuleButton,
  Field,
  FieldGroup,
  NumberStepper,
  RangeField,
  Section,
  SegmentedControl,
  TextArea,
  TextInput,
  Toggle,
} from "./components/ui";
import type {
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
  const [mediaIds, setMediaIds] = useState<number[]>([]);
  const [writeAsChannel, setWriteAsChannel] = useState(false);
  const [verifyAfterPost, setVerifyAfterPost] = useState(false);
  const [verifyDelaySec, setVerifyDelaySec] = useState(300);

  // Показываем аккаунты в ЛЮБОМ статусе — «не идеальные» помечаем. Для
  // «добавить всю группу» дальше берём только свободных (pool).
  const groups = useQuery({ queryKey: ["projects"], queryFn: projectsApi.list });
  const allAccounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const pool = allAccounts;
  const personas = useQuery({ queryKey: ["personas"], queryFn: catalogApi.personas });
  const delayPresets = useQuery({ queryKey: ["delay-presets"], queryFn: delayPresetsApi.list });

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

  const anyNonIdealSelected = (allAccounts.data ?? []).some(
    (a) => selected.has(a.id) && accountWorkWarning(a.status) != null,
  );

  // Аккаунты, которые реально прикрепятся: сервер требует status === 'pool'
  // (warming/cooldown/assigned attach отклоняет с 409). Раньше пользователь
  // выбирал warming-аккаунт, бэкенд его отбрасывал, но кампания создавалась
  // «пустой» без явного сигнала.
  const attachableIds = (allAccounts.data ?? [])
    .filter((a) => selected.has(a.id) && a.status === "pool")
    .map((a) => a.id);
  const skippedCount = selected.size - attachableIds.length;

  const valid =
    name.trim() !== "" &&
    prompt.trim() !== "" &&
    delayMin <= delayMax &&
    (selectionMode !== "keywords" || keywordsList.length > 0) &&
    attachableIds.length > 0;

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
      if (attachImage && mediaIds.length > 0) {
        try {
          await commentingApi.setMedia(camp.id, mediaIds);
        } catch {
          /* некритично: картинки можно прикрепить позже в деталях кампании */
        }
      }
      // Прикрепляем только pool-аккаунты (сервер отклонит остальные с 409).
      // Собираем результаты, чтобы при полном провале удалить созданную кампанию
      // и показать пользователю ошибку — иначе он видит «пустую» кампанию без
      // понимания, что пошло не так.
      let attached = 0;
      const failedIds: number[] = [];
      for (const id of attachableIds) {
        const override =
          selectionMode === "probability" ? perAccountProbability[id] ?? null : null;
        try {
          await commentingApi.attach(camp.id, id, {
            probability_override: override,
          });
          attached += 1;
        } catch {
          failedIds.push(id);
        }
      }
      if (attached === 0) {
        // Ни один не прошёл — чистим созданную кампанию и бросаем, чтобы
        // пользователь остался на экране создания с текущими данными.
        try {
          await commentingApi.remove(camp.id);
        } catch {
          /* если не удалось удалить — не критично, пользователь увидит её
             в списке и сможет удалить вручную */
        }
        throw new Error(
          failedIds.length > 0
            ? "Ни один аккаунт не удалось привязать (отказ сервера). Проверьте статусы аккаунтов."
            : "Не удалось привязать аккаунты.",
        );
      }
      return { camp, attached, failedIds, skipped: skippedCount };
    },
    onSuccess: ({ camp }) => {
      haptic("light");
      navigate(`/modules/commenting/campaigns/${camp.id}`);
    },
  });

  const setDelayMinClamped = (v: number) => {
    setDelayMin(v);
    if (v > delayMax) setDelayMax(v);
  };

  return (
    <div className="flex min-h-full flex-col pb-28 pt-1 lg:pb-10">
      <button
        onClick={() => navigate("/tasks")}
        className="mb-4 inline-flex w-fit items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Кампании
      </button>
      <h1 className="screen-title mb-6">Новая кампания</h1>

      <AiProtectionCard />

      <div className="lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
      <div className="min-w-0">
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
            hint="~25% комментариев уйдут стикером. Выбирать не нужно — берём автоматически первый стикерпак, сохранённый в самом Telegram-аккаунте. Своего пака нет — просто уйдёт текст."
            checked={useStickers}
            onChange={setUseStickers}
          />
          <ToggleRow
            label="Картинка к комментарию"
            hint="Приложится случайная картинка (~40%) из выбранных ниже. Можно дозагрузить позже в деталях кампании."
            checked={attachImage}
            onChange={setAttachImage}
          />
          {attachImage && <MediaPickerInline selected={mediaIds} onChange={setMediaIds} />}
          <ToggleRow
            label="Писать от имени канала"
            hint="Настраивать некого — на каждую публикацию система сама проверяет права post_messages у аккаунта в этом канале: есть права → коммент от канала, нет → автоматически от аккаунта."
            checked={writeAsChannel}
            onChange={setWriteAsChannel}
          />
          <ToggleRow
            label="Контроль удаления комментариев"
            hint={`Через ${verifyDelaySec}с тот же аккаунт перечитывает свой коммент; если модератор снял — пометим и уведомим.`}
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
            {postScope === "existing"
              ? "Пройдёмся по истории каждого канала и попробуем прокомментировать до 200 подходящих постов (не по одному разу — учитывается лог)."
              : "Сначала пройдёмся по истории канала (до 200 постов), затем комментируем новые посты по мере появления."}
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
        {/* Однострочные подписи + items-end: поля всегда на одной высоте. */}
        <div className="mt-3 grid grid-cols-2 items-end gap-3">
          <Field label="Макс. комментариев">
            <TextInput
              inputMode="numeric"
              value={maxComments}
              onChange={(e) => setMaxComments(e.target.value.replace(/\D/g, ""))}
              placeholder="Без лимита"
              className="nums text-center"
            />
          </Field>
          <FieldGroup label="Мин. слов в комменте">
            <NumberStepper
              value={String(minWords)}
              onChange={(v) => setMinWords(Number(v) || 0)}
              min={0}
              ariaLabel="Минимум слов"
            />
          </FieldGroup>
          {workMode === "by_time_window" && (
            <>
              <FieldGroup label="Окно после поста">
                <NumberStepper
                  value={String(windowAfterPost)}
                  onChange={(v) => setWindowAfterPost(Number(v) || 0)}
                  step={60}
                  min={60}
                  suffix="сек"
                  ariaLabel="Окно после публикации, сек"
                />
              </FieldGroup>
              <FieldGroup label="Пауза между комментами">
                <NumberStepper
                  value={String(pauseBetween)}
                  onChange={(v) => setPauseBetween(Number(v) || 0)}
                  step={10}
                  min={0}
                  suffix="сек"
                  ariaLabel="Пауза между комментариями, сек"
                />
              </FieldGroup>
            </>
          )}
        </div>
        <p className="px-1 text-[12px] text-text-tertiary">
          {workMode === "by_time_window"
            ? "Аккаунты комментируют только пока не истекло окно после публикации поста и не чаще, чем раз в паузу. Короткие ответы ИИ перегенерирует (до 3 попыток)."
            : "Считаются только опубликованные комментарии. Короткие ответы ИИ перегенерирует (до 3 попыток), иначе коммент пропускается."}
        </p>
      </Section>

      </div>
      <div className="min-w-0">
      <Section title="Окно активности">
        <div className="flex gap-2">
          <Field label="С">
            <TimeField value={start} onChange={setStart} />
          </Field>
          <Field label="До">
            <TimeField value={end} onChange={setEnd} />
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
                      {raw} · {kind === "folder" ? "папка" : kind === "invite" ? "приглашение" : "канал"}
                    </span>
                  );
                })}
              </div>
            )}
            <p className="mt-2 px-1 text-[12px] text-text-tertiary">
              Каждый аккаунт кампании получит эти каналы в мониторинг. Папки
              (`t.me/addlist/…`) раскрываются в каналы, но только при режиме
              «Подписаться + уведомить» — чтобы увидеть каналы папки, в неё нужно вступить.
            </p>
          </div>
        ) : (
          <p className="mt-2 px-1 text-[12px] text-text-tertiary">
            Каждый аккаунт комментирует каналы, на которые он уже подписан в
            Telegram (до 200 каналов, только с открытыми комментариями).
          </p>
        )}
        <div className="mt-4">
          <FieldGroup label="Если аккаунт не подписан">
            <SegmentedControl
              options={[
                { value: "notify_only", label: "Только уведомить" },
                { value: "subscribe_and_notify", label: "Подписаться + уведомить" },
              ]}
              value={onNotSubscribed}
              onChange={(v) => setOnNotSubscribed(v as OnNotSubscribedAction)}
            />
          </FieldGroup>
          <p className="px-1 text-[12px] text-text-tertiary">
            Уведомление приходит в Telegram-бот и появляется на главной и в
            деталях кампании. Каналы, к которым пропал доступ, автоматически
            попадают в чёрный список кампании.
          </p>
        </div>
      </Section>

      <Section title="Аккаунты">
        <AddGroupBar
          groups={groups.data ?? []}
          pool={(pool.data ?? []).filter((a) => a.status === "pool")}
          all={allAccounts.data ?? []}
          onAdd={(ids) =>
            setSelected((s) => {
              const n = new Set(s);
              ids.forEach((id) => n.add(id));
              return n;
            })
          }
        />
        {anyNonIdealSelected && (
          <div className="mt-3 flex items-start gap-2 rounded-chip border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-[12px] text-status-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
            <span>
              Выбрано {selected.size} аккаунтов, но прикрепится только{" "}
              <strong>{attachableIds.length}</strong>: остальные {skippedCount} не из пула
              (на прогреве / заняты / в кулдауне / выведены). Прикрепить их можно
              позже из экрана кампании, когда они освободятся.
            </span>
          </div>
        )}
        {selected.size > 0 && attachableIds.length === 0 && (
          <div className="mt-3 flex items-start gap-2 rounded-chip border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-[12px] text-status-critical">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
            <span>
              Ни один из выбранных аккаунтов нельзя прикрепить сейчас (все не в
              пуле). Кампания не будет создана — выберите хотя бы один из пула.
            </span>
          </div>
        )}
        {pool.data && pool.data.length > 0 ? (
          <div className="mt-3 max-h-[420px] overflow-y-auto rounded-chip border border-hairline bg-surface-1/40 p-2 [scrollbar-width:thin]">
          <div className="flex flex-col gap-2">
            {sortForWork(pool.data).map((a) => {
              const isSelected = selected.has(a.id);
              return (
                <div key={a.id}>
                  <AccountPickRow
                    account={a}
                    selected={isSelected}
                    note={accountWorkWarning(a.status) ?? undefined}
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
          </div>
        ) : (
          <p className="mt-3 text-[13px] text-text-tertiary">Аккаунтов пока нет.</p>
        )}
      </Section>

      </div>
      </div>

      {create.isError && (
        <ErrorBanner
          className="mb-3"
          message={humanizeError(create.error, "Не удалось создать кампанию.")}
        />
      )}

      <StickyActionBar>
        <CapsuleButton
          variant={valid ? "accent" : "secondary"}
          disabled={!valid || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending
            ? "Создаём…"
            : attachableIds.length > 0
              ? `Создать кампанию (${attachableIds.length} ${attachableIds.length === 1 ? "аккаунт" : "аккаунтов"})`
              : "Создать кампанию"}
        </CapsuleButton>
      </StickyActionBar>
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