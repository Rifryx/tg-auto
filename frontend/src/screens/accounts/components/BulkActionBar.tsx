import { useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Globe,
  Images,
  LogOut,
  ShieldAlert,
  Sparkles,
  Stethoscope,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
import { accountsApi, bulkApi } from "../../../shared/accounts";
import { haptic } from "../../../shared/tg";
import { showToast } from "../../../shared/toast";
import { PoolProfileSheet } from "./PoolProfileSheet";
import { ConfirmDialog } from "./ui";

/* Панель массовых действий (этап 2). Появляется, когда выбран ≥1 аккаунт.
 *
 * Действия через очередь (health-check / bulk-jobs) только ставятся в работу —
 * показываем toast о запуске; прогресс виден на карточках аккаунтов. Вывод и
 * удаление — синхронные per-account вызовы (цикл), с подтверждением. */
export function BulkActionBar({
  selectedIds,
  onClear,
}: {
  selectedIds: number[];
  onClear: () => void;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<null | "retire" | "delete">(null);
  const [poolOpen, setPoolOpen] = useState(false);

  const n = selectedIds.length;
  if (n === 0) return null;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["accounts"] });

  const checkValid = async (includeSpam: boolean) => {
    setBusy(true);
    try {
      const r = await accountsApi.healthCheckBulk(selectedIds, includeSpam);
      showToast(
        `Проверка запущена: ${r.enqueued.length}` +
          (r.throttled.length ? `, пропущено ${r.throttled.length}` : ""),
        "success",
      );
      haptic("light");
    } catch {
      showToast("Не удалось запустить проверку", "error");
    } finally {
      setBusy(false);
    }
  };

  const runJob = async (action: string, label: string) => {
    setBusy(true);
    try {
      await bulkApi.create(action, selectedIds, action === "assign_proxy" ? { mode: "pool" } : {});
      showToast(`${label}: задание запущено для ${n}`, "success");
      haptic("light");
    } catch {
      showToast(`Не удалось: ${label}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const runPool = async (payload: Record<string, unknown>) => {
    setBusy(true);
    try {
      await bulkApi.create("apply_profile_pool", selectedIds, payload);
      showToast(`Профиль из пула: задание запущено для ${n}`, "success");
      haptic("light");
      setPoolOpen(false);
    } catch {
      showToast("Не удалось запустить «Профиль из пула»", "error");
    } finally {
      setBusy(false);
    }
  };

  const exportSessions = async () => {
    setBusy(true);
    try {
      const data = await accountsApi.exportSessions(selectedIds);
      if (data.length === 0) {
        showToast("Нет сессий для экспорта", "error");
        return;
      }
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `sessions-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Экспортировано: ${data.length}`, "success");
      haptic("light");
    } catch {
      showToast("Не удалось экспортировать", "error");
    } finally {
      setBusy(false);
    }
  };

  const perAccount = async (
    fn: (id: number) => Promise<unknown>,
    label: string,
  ) => {
    setBusy(true);
    const results = await Promise.allSettled(selectedIds.map(fn));
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;
    showToast(
      `${label}: готово ${ok}${failed ? `, ошибок ${failed}` : ""}`,
      failed ? "error" : "success",
    );
    haptic(failed ? "rigid" : "light");
    invalidate();
    onClear();
    setBusy(false);
    setConfirm(null);
  };

  return (
    <>
      <div className="fixed inset-x-0 bottom-[76px] z-40 px-3 lg:bottom-4 lg:left-[var(--sidebar-w,0px)]">
        <div className="mx-auto max-w-[640px] rounded-card border border-strong bg-bg-elevated p-2 shadow-lg">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[13px] font-semibold text-text-primary">
              Выбрано: {n}
            </span>
            <button
              onClick={onClear}
              className="flex items-center gap-1 text-[13px] text-text-secondary active:text-text-primary"
            >
              <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
              Снять
            </button>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <ActionChip
              icon={<Stethoscope className="h-4 w-4" strokeWidth={1.8} />}
              label="Проверить"
              disabled={busy}
              onClick={() => checkValid(false)}
            />
            <ActionChip
              icon={<ShieldAlert className="h-4 w-4" strokeWidth={1.8} />}
              label="Спамблок"
              disabled={busy}
              onClick={() => checkValid(true)}
            />
            <ActionChip
              icon={<Sparkles className="h-4 w-4" strokeWidth={1.8} />}
              label="Профиль ИИ"
              disabled={busy}
              onClick={() => runJob("generate_and_apply_profile", "Профиль ИИ")}
            />
            <ActionChip
              icon={<Images className="h-4 w-4" strokeWidth={1.8} />}
              label="Профиль из пула"
              disabled={busy}
              onClick={() => setPoolOpen(true)}
            />
            <ActionChip
              icon={<Globe className="h-4 w-4" strokeWidth={1.8} />}
              label="Раздать прокси"
              disabled={busy}
              onClick={() => runJob("assign_proxy", "Прокси")}
            />
            <ActionChip
              icon={<Download className="h-4 w-4" strokeWidth={1.8} />}
              label="Экспорт"
              disabled={busy}
              onClick={exportSessions}
            />
            <ActionChip
              icon={<LogOut className="h-4 w-4" strokeWidth={1.8} />}
              label="Сбросить сессии"
              disabled={busy}
              onClick={() => runJob("logout_other_sessions", "Сброс сессий")}
            />
            <ActionChip
              label="Вывести"
              disabled={busy}
              onClick={() => setConfirm("retire")}
            />
            <ActionChip
              icon={<Trash2 className="h-4 w-4" strokeWidth={1.8} />}
              label="Удалить"
              danger
              disabled={busy}
              onClick={() => setConfirm("delete")}
            />
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirm === "retire"}
        title={`Вывести ${n} акк.?`}
        message="Аккаунты перейдут в статус «Выведен» и исчезнут из активных фильтров."
        confirmLabel="Вывести"
        danger
        busy={busy}
        onConfirm={() => perAccount((id) => accountsApi.retire(id), "Вывод")}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        title={`Удалить ${n} акк.?`}
        message="Аккаунты и все их данные будут удалены безвозвратно."
        confirmLabel="Удалить"
        danger
        busy={busy}
        onConfirm={() => perAccount((id) => accountsApi.remove(id), "Удаление")}
        onCancel={() => setConfirm(null)}
      />
      {poolOpen && (
        <PoolProfileSheet
          count={n}
          busy={busy}
          onApply={runPool}
          onCancel={() => setPoolOpen(false)}
        />
      )}
    </>
  );
}

function ActionChip({
  icon,
  label,
  onClick,
  disabled,
  danger,
}: {
  icon?: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex shrink-0 items-center gap-1.5 rounded-pill border px-3 py-2 text-[13px] font-medium transition-opacity active:opacity-70 disabled:opacity-40 ${
        danger
          ? "border-hairline bg-surface-1 text-status-critical"
          : "border-hairline bg-surface-1 text-text-primary"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
