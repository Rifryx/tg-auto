import { useEffect, useState } from "react";
import type {
  Campaign,
  CampaignUpdateBody,
  PostScope,
  PostSelectionMode,
  WorkMode,
} from "../types";
import {
  Field,
  FieldGroup,
  NumberStepper,
  RangeField,
  Section,
  SegmentedControl,
  TextArea,
  TextInput,
} from "./ui";

/* «Условия комментирования» в экране кампании (§ самое важное из правок).
   Раньше выбор режимов делался ТОЛЬКО при создании и нигде потом не был виден
   и не редактировался. Теперь те же настройки, что и на создании, видны и
   меняются прямо здесь — автосейвом (PATCH /campaigns/{id}). */
export function CommentingRulesSection({
  campaign,
  onSave,
}: {
  campaign: Campaign;
  onSave: (body: CampaignUpdateBody) => void;
}) {
  // Локальные копии редактируемых полей; ресинкаются, когда кампания
  // перезагрузилась после сохранения.
  const [keywords, setKeywords] = useState(campaign.keywords.join("\n"));
  const [probability, setProbability] = useState(campaign.probability_percent);
  const [minWords, setMinWords] = useState(campaign.min_words);
  const [maxComments, setMaxComments] = useState(
    campaign.max_comments != null ? String(campaign.max_comments) : "",
  );
  const [maxWords, setMaxWords] = useState(
    campaign.max_words != null ? String(campaign.max_words) : "",
  );
  const [existingMaxPosts, setExistingMaxPosts] = useState(String(campaign.existing_scope_max_posts));
  const [existingMaxAge, setExistingMaxAge] = useState(
    campaign.existing_scope_max_age_days != null ? String(campaign.existing_scope_max_age_days) : "",
  );
  const [windowAfterPost, setWindowAfterPost] = useState(campaign.window_after_post_sec ?? 3600);
  const [pauseBetween, setPauseBetween] = useState(campaign.pause_between_sec ?? 60);
  useEffect(() => setKeywords(campaign.keywords.join("\n")), [campaign.keywords]);
  useEffect(() => setProbability(campaign.probability_percent), [campaign.probability_percent]);
  useEffect(() => setMinWords(campaign.min_words), [campaign.min_words]);
  useEffect(
    () => setMaxComments(campaign.max_comments != null ? String(campaign.max_comments) : ""),
    [campaign.max_comments],
  );
  useEffect(
    () => setMaxWords(campaign.max_words != null ? String(campaign.max_words) : ""),
    [campaign.max_words],
  );
  useEffect(
    () => setExistingMaxPosts(String(campaign.existing_scope_max_posts)),
    [campaign.existing_scope_max_posts],
  );
  useEffect(
    () =>
      setExistingMaxAge(
        campaign.existing_scope_max_age_days != null
          ? String(campaign.existing_scope_max_age_days)
          : "",
      ),
    [campaign.existing_scope_max_age_days],
  );
  useEffect(
    () => setWindowAfterPost(campaign.window_after_post_sec ?? 3600),
    [campaign.window_after_post_sec],
  );
  useEffect(
    () => setPauseBetween(campaign.pause_between_sec ?? 60),
    [campaign.pause_between_sec],
  );

  const commitKeywords = () => {
    const list = keywords
      .split(/[\n|]/)
      .map((s) => s.trim())
      .filter(Boolean);
    onSave({ keywords: list });
  };
  const commitMaxComments = () => {
    const n = maxComments.trim() ? Number(maxComments) : null;
    if (n === campaign.max_comments) return;
    onSave({ max_comments: n && n > 0 ? n : null });
  };
  const commitMaxWords = () => {
    const n = maxWords.trim() ? Number(maxWords) : null;
    if (n === campaign.max_words) return;
    onSave({ max_words: n && n > 0 ? n : null });
  };
  const commitExistingMaxPosts = () => {
    const n = Number(existingMaxPosts) || campaign.existing_scope_max_posts;
    if (n === campaign.existing_scope_max_posts) return;
    onSave({ existing_scope_max_posts: Math.max(1, n) });
  };
  const commitExistingMaxAge = () => {
    const n = existingMaxAge.trim() ? Number(existingMaxAge) : null;
    if (n === campaign.existing_scope_max_age_days) return;
    onSave({ existing_scope_max_age_days: n && n > 0 ? n : null });
  };

  return (
    <Section title="Условия комментирования">
      <div className="card flex flex-col gap-4 p-4">
        {/* Какие посты комментировать */}
        <div>
          <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Режим отбора постов</p>
          <SegmentedControl<PostSelectionMode>
            options={[
              { value: "all", label: "Все" },
              { value: "keywords", label: "По словам" },
              { value: "probability", label: "Вероятность" },
            ]}
            value={campaign.post_selection_mode}
            onChange={(v) => onSave({ post_selection_mode: v })}
          />
          {campaign.post_selection_mode === "keywords" && (
            <div className="mt-3">
              <Field
                label="Ключевые слова"
                hint={<span className="text-[11px] text-text-tertiary">одно в строке или через `|`</span>}
              >
                <TextArea
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  onBlur={commitKeywords}
                  placeholder={"крипта\nчат\nсообщество"}
                />
              </Field>
            </div>
          )}
          {campaign.post_selection_mode === "probability" && (
            <div className="mt-3">
              <RangeField
                label="Вероятность комментирования"
                value={probability}
                min={0}
                max={100}
                unit="%"
                onChange={setProbability}
                onCommit={() => onSave({ probability_percent: probability })}
              />
            </div>
          )}
        </div>

        {/* Охват постов */}
        <div>
          <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Какие посты</p>
          <SegmentedControl<PostScope>
            options={[
              { value: "new", label: "Новые" },
              { value: "existing", label: "Существующие" },
              { value: "mixed", label: "Сначала старые" },
            ]}
            value={campaign.post_scope}
            onChange={(v) => onSave({ post_scope: v })}
          />
          {campaign.post_scope !== "new" && (
            <div className="mt-3 grid grid-cols-2 items-end gap-3">
              <Field label="Глубина (постов)">
                <TextInput
                  inputMode="numeric"
                  value={existingMaxPosts}
                  onChange={(e) => setExistingMaxPosts(e.target.value.replace(/\D/g, ""))}
                  onBlur={commitExistingMaxPosts}
                  placeholder="200"
                  className="nums text-center"
                />
              </Field>
              <Field label="Не старше (дней)">
                <TextInput
                  inputMode="numeric"
                  value={existingMaxAge}
                  onChange={(e) => setExistingMaxAge(e.target.value.replace(/\D/g, ""))}
                  onBlur={commitExistingMaxAge}
                  placeholder="Без ограничения"
                  className="nums text-center"
                />
              </Field>
              <p className="col-span-2 px-1 text-[12px] text-text-tertiary">
                Чтобы не комментить тысячу старых постов: берём не глубже N постов
                и не старше указанного возраста.
              </p>
            </div>
          )}
        </div>

        {/* Режим работы */}
        <div>
          <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Режим работы</p>
          <SegmentedControl<WorkMode>
            options={[
              { value: "by_count", label: "По количеству" },
              { value: "by_time_window", label: "По времени" },
            ]}
            value={campaign.work_mode}
            onChange={(v) => onSave({ work_mode: v })}
          />
          {campaign.work_mode === "by_time_window" && (
            <div className="mt-3 grid grid-cols-2 items-end gap-3">
              <FieldGroup label="Окно после поста">
                <NumberStepper
                  value={String(windowAfterPost)}
                  onChange={(v) => setWindowAfterPost(Number(v) || 0)}
                  onCommit={(next) => onSave({ window_after_post_sec: Number(next) || 0 })}
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
                  onCommit={(next) => onSave({ pause_between_sec: Number(next) || 0 })}
                  step={10}
                  min={0}
                  suffix="сек"
                  ariaLabel="Пауза между комментариями, сек"
                />
              </FieldGroup>
              <p className="col-span-2 px-1 text-[12px] text-text-tertiary">
                Аккаунты комментируют только пока не истекло окно после публикации
                поста и не чаще, чем раз в паузу.
              </p>
            </div>
          )}
        </div>

        {/* Лимиты */}
        <Field label="Макс. комментариев (за всё время)">
          <TextInput
            inputMode="numeric"
            value={maxComments}
            onChange={(e) => setMaxComments(e.target.value.replace(/\D/g, ""))}
            onBlur={commitMaxComments}
            placeholder="Без лимита"
            className="nums text-center"
          />
        </Field>
        <RangeField
          label="Мин. слов в комменте"
          value={minWords}
          min={0}
          max={30}
          unit="слов"
          onChange={setMinWords}
          onCommit={() => onSave({ min_words: minWords })}
        />
        <Field label="Макс. слов в комменте">
          <TextInput
            inputMode="numeric"
            value={maxWords}
            onChange={(e) => setMaxWords(e.target.value.replace(/\D/g, ""))}
            onBlur={commitMaxWords}
            placeholder="Без лимита"
            className="nums text-center"
          />
        </Field>
      </div>
    </Section>
  );
}
