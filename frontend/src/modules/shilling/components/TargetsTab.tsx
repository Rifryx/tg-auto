import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Clock,
  Database,
  FileUp,
  List,
  Plus,
  X,
} from "lucide-react";
import { useRef, useState } from "react";
import { showToast } from "../../../shared/toast";
import { shillingApi } from "../api";
import type { Target, TargetStatus } from "../types";

export function TargetsTab({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const [input, setInput] = useState("");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const targets = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "targets"],
    queryFn: () => shillingApi.targets(campaignId),
    refetchInterval: (q) => {
      const data = q.state.data as Target[] | undefined;
      return data?.some((t) => t.status === "pending") ? 3000 : false;
    },
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "targets"] });

  const add = useMutation({
    mutationFn: (raws: string[]) => shillingApi.addTargets(campaignId, raws),
    onSuccess: (created, vars) => {
      invalidate();
      if (created.length < vars.length) {
        showToast(`Добавлено ${created.length} из ${vars.length} (дубли пропущены)`, "info");
      }
    },
  });
  const remove = useMutation({
    mutationFn: (targetId: number) => shillingApi.removeTarget(campaignId, targetId),
    onSuccess: invalidate,
  });

  const submitOne = () => {
    const v = input.trim();
    if (!v) return;
    if (!isValidRef(v)) {
      showToast("Формат: @username или t.me/…", "error");
      return;
    }
    add.mutate([v]);
    setInput("");
  };

  const submitBulk = () => {
    const raws = bulkText
      .split(/[\n,]/)
      .map((t) => t.trim())
      .filter(Boolean);
    if (raws.length) add.mutate(raws);
    setBulkText("");
    setBulkOpen(false);
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const raws = text
      .split(/[\n,;]/)
      .map((t) => t.trim())
      .filter(Boolean);
    if (raws.length) add.mutate(raws);
    if (fileRef.current) fileRef.current.value = "";
  };

  const list: Target[] = targets.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[14px] font-medium text-text-primary">
            Целевые каналы <span className="text-text-tertiary">· {list.length}</span>
          </p>
        </div>

        {/* Чипы */}
        {list.length > 0 ? (
          <div className="mb-3 flex flex-wrap gap-2">
            {list.map((t) => (
              <TargetChip key={t.id} target={t} onRemove={() => remove.mutate(t.id)} />
            ))}
          </div>
        ) : (
          <p className="mb-3 text-[13px] text-text-tertiary">Целей пока нет.</p>
        )}

        {/* Поле добавления */}
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitOne()}
            placeholder="@username или t.me/… — Enter"
            className="h-11 flex-1 rounded-chip border border-hairline bg-surface-1 px-4 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
          />
          <button
            onClick={submitOne}
            disabled={!input.trim() || add.isPending}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-chip bg-accent text-accent-on active:opacity-80 disabled:opacity-40"
            aria-label="Добавить"
          >
            <Plus className="h-5 w-5" strokeWidth={2.2} aria-hidden />
          </button>
        </div>
      </div>

      {/* Действия */}
      <div className="flex flex-wrap gap-2">
        <ActionButton icon={List} label="Вставить списком" onClick={() => setBulkOpen((v) => !v)} />
        <ActionButton icon={FileUp} label="Импорт из файла" onClick={() => fileRef.current?.click()} />
        <ActionButton icon={Database} label="Из базы" disabled soon />
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.csv"
          onChange={onFile}
          className="hidden"
        />
      </div>

      {bulkOpen && (
        <div className="card p-4">
          <textarea
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder="По одной ссылке в строке (или через запятую)"
            rows={5}
            className="w-full resize-y rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[14px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={() => {
                setBulkOpen(false);
                setBulkText("");
              }}
              className="h-9 rounded-pill bg-surface-2 px-4 text-[13px] text-text-secondary active:text-text-primary"
            >
              Отмена
            </button>
            <button
              onClick={submitBulk}
              disabled={!bulkText.trim() || add.isPending}
              className="h-9 rounded-pill bg-accent px-4 text-[13px] font-medium text-accent-on active:opacity-80 disabled:opacity-40"
            >
              Добавить
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const STATUS_ICON: Record<TargetStatus, { icon: typeof Check; cls: string }> = {
  resolved: { icon: Check, cls: "text-status-active" },
  pending: { icon: Clock, cls: "text-text-tertiary" },
  error: { icon: AlertTriangle, cls: "text-status-critical" },
};

function TargetChip({ target, onRemove }: { target: Target; onRemove: () => void }) {
  const [showErr, setShowErr] = useState(false);
  const meta = STATUS_ICON[target.status];
  const Icon = meta.icon;
  const label = target.title || target.raw_input;
  return (
    <div className="relative">
      <div className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 py-1.5 pl-2.5 pr-1.5">
        <button
          type="button"
          onClick={() => target.status === "error" && setShowErr((v) => !v)}
          className={meta.cls}
          aria-label={target.status}
        >
          <Icon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </button>
        <span className="max-w-[160px] truncate text-[13px] text-text-primary">{label}</span>
        <button
          onClick={onRemove}
          aria-label="Удалить"
          className="text-text-tertiary active:text-status-critical"
        >
          <X className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
        </button>
      </div>
      {showErr && target.last_error && (
        <div className="absolute left-0 top-full z-10 mt-1 w-56 rounded-chip border border-hairline bg-bg-elevated px-3 py-2 text-[12px] text-status-critical shadow-lg">
          {target.last_error}
        </div>
      )}
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  soon,
}: {
  icon: typeof Check;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  soon?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3.5 py-2 text-[13px] text-text-secondary active:text-text-primary disabled:opacity-50"
    >
      <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
      {label}
      {soon && (
        <span className="rounded-pill bg-surface-1 px-1.5 py-0.5 text-[10px] text-text-tertiary">
          скоро
        </span>
      )}
    </button>
  );
}

/* Валидация ввода цели: @username, t.me/…, telegram.me/…, или голый username. */
function isValidRef(v: string): boolean {
  if (/^-?\d+$/.test(v)) return true; // chat_id
  if (/^@[\w\d_]{3,}$/.test(v)) return true;
  if (/(?:https?:\/\/)?(?:t|telegram)\.me\/.+/i.test(v)) return true;
  if (/^[\w\d_]{3,}$/.test(v)) return true; // голый username
  return false;
}
