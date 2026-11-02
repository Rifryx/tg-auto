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
  useEffect(() => setKeywords(campaign.keywords.join("\n")), [campaign.keywords]);
  useEffect(() => setProbability(campaign.probability_percent), [campaign.probability_percent]);
  useEffect(() => setMinWords(campaign.min_words), [campaign.min_words]);
  useEffect(
    () => setMaxComments(campaign.max_comments != null ? String(campaign.max_comments) : ""),
    [campaign.max_comments],
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
      </div>
    </Section>
  );
}
