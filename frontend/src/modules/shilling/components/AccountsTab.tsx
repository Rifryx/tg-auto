import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Lightbulb, Plus, X } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { banRiskApi, riskDotClass, RISK_LEVEL_LABEL } from "../../../shared/banRisk";
import type { RiskLevel } from "../../../shared/banRisk";
import { maskPhone } from "../../../shared/format";
import { AccountPickerSheet } from "../../commenting/components/AccountPickerSheet";
import { Select } from "../../../shared/Select";
import { shillingApi } from "../api";
import type { CampaignAccount, Role } from "../types";

export function AccountsTab({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [dragId, setDragId] = useState<number | null>(null);

  const links = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "accounts"],
    queryFn: () => shillingApi.accounts(campaignId),
  });
  const allAccounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });
  const scenario = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "scenario"],
    queryFn: () => shillingApi.scenario(campaignId),
    retry: false,
  });
  const roles = useQuery({
    queryKey: ["shilling", "scenario", scenario.data?.id, "roles"],
    queryFn: () => shillingApi.roles(scenario.data!.id),
    enabled: scenario.data?.id != null,
  });
  const highRisk = useQuery({
    queryKey: ["ban-risk", "high"],
    queryFn: () => banRiskApi.listHighRisk({ limit: 200 }),
  });

  const riskById = new Map<number, RiskLevel>(
    (highRisk.data ?? []).map((r) => [r.account_id, r.risk_level]),
  );
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId, "accounts"] });

  const setReserve = useMutation({
    mutationFn: (p: { accountId: number; is_reserve: boolean }) =>
      shillingApi.patchAccount(campaignId, p.accountId, { is_reserve: p.is_reserve }),
    onSuccess: invalidate,
  });
  const setRole = useMutation({
    mutationFn: (p: { accountId: number; role_id: number | null }) =>
      shillingApi.patchAccount(campaignId, p.accountId, { role_id: p.role_id }),
    onSuccess: invalidate,
  });
  const detach = useMutation({
    mutationFn: (accountId: number) => shillingApi.detach(campaignId, accountId),
    onSuccess: invalidate,
  });
  const attach = useMutation({
    mutationFn: (ids: number[]) =>
      Promise.all(ids.map((id) => shillingApi.attach(campaignId, { account_id: id }))),
    onSuccess: () => {
      setSheetOpen(false);
      invalidate();
    },
  });

  const linkList: CampaignAccount[] = links.data ?? [];
  const primary = linkList.filter((l) => !l.is_reserve);
  const reserve = linkList.filter((l) => l.is_reserve);
  const attachedIds = linkList.map((l) => l.account_id);
  const accById = new Map((allAccounts.data ?? []).map((a) => [a.id, a]));
  const roleList: Role[] = roles.data ?? [];

  // Инсайт: основной аккаунт в критической зоне → предложить в резерв.
  const criticalPrimary = primary.filter((l) => riskById.get(l.account_id) === "critical");

  const drop = (toReserve: boolean) => {
    if (dragId == null) return;
    const link = linkList.find((l) => l.account_id === dragId);
    if (link && link.is_reserve !== toReserve) {
      setReserve.mutate({ accountId: dragId, is_reserve: toReserve });
    }
    setDragId(null);
  };

  const renderCard = (link: CampaignAccount) => {
    const acc = accById.get(link.account_id);
    const level = riskById.get(link.account_id) ?? "low";
    return (
      <div
        key={link.account_id}
        draggable
        onDragStart={() => setDragId(link.account_id)}
        onDragEnd={() => setDragId(null)}
        className="card flex flex-col gap-2 p-3"
      >
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${riskDotClass(level)}`}
            title={`Риск: ${RISK_LEVEL_LABEL[level]}`}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate text-[14px] text-text-primary nums">
            {acc ? maskPhone(acc.phone) : `Аккаунт #${link.account_id}`}
          </span>
          <button
            onClick={() =>
              setReserve.mutate({ accountId: link.account_id, is_reserve: !link.is_reserve })
            }
            aria-label={link.is_reserve ? "В основные" : "В резерв"}
            title={link.is_reserve ? "В основные" : "В резерв"}
            className="text-text-tertiary active:text-text-primary"
          >
            <ArrowLeftRight className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
          </button>
          <button
            onClick={() => detach.mutate(link.account_id)}
            aria-label="Отвязать"
            className="text-text-tertiary active:text-status-critical"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>
        {!link.is_reserve && (
          <Select
            value={link.role_id != null ? String(link.role_id) : ""}
            onChange={(v) =>
              setRole.mutate({ accountId: link.account_id, role_id: v === "" ? null : Number(v) })
            }
            placeholder="Роль не назначена"
            options={[
              { value: "", label: "Роль не назначена" },
              ...roleList.map((r) => ({ value: String(r.id), label: r.name })),
            ]}
          />
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {criticalPrimary.length > 0 && (
        <div className="card flex items-start gap-2 border border-status-warning/40 p-3">
          <Lightbulb className="h-4 w-4 shrink-0 text-status-warning" strokeWidth={2} aria-hidden />
          <p className="text-[13px] text-text-secondary">
            {criticalPrimary.length === 1
              ? "1 основной аккаунт в критической зоне риска"
              : `${criticalPrimary.length} основных аккаунта в критической зоне`}{" "}
            — лучше вынести в резерв.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Column
          title="Основные"
          count={primary.length}
          onDrop={() => drop(false)}
          highlight={dragId != null}
        >
          {primary.length === 0 ? (
            <Empty text="Перетащите сюда аккаунты" />
          ) : (
            primary.map(renderCard)
          )}
        </Column>
        <Column
          title="Резерв"
          count={reserve.length}
          onDrop={() => drop(true)}
          highlight={dragId != null}
        >
          {reserve.length === 0 ? <Empty text="Резерв пуст" /> : reserve.map(renderCard)}
        </Column>
      </div>

      <button
        onClick={() => setSheetOpen(true)}
        className="inline-flex h-10 items-center justify-center gap-1.5 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80"
      >
        <Plus className="h-4 w-4" strokeWidth={2} aria-hidden />
        Добавить из пула
      </button>

      <AccountPickerSheet
        open={sheetOpen}
        excludeIds={attachedIds}
        busy={attach.isPending}
        onClose={() => setSheetOpen(false)}
        onAdd={(ids) => attach.mutate(ids)}
      />
    </div>
  );
}

function Column({
  title,
  count,
  children,
  onDrop,
  highlight,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  onDrop: () => void;
  highlight: boolean;
}) {
  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      className={[
        "rounded-card border p-3 transition-colors",
        highlight ? "border-accent/50 bg-surface-1" : "border-hairline",
      ].join(" ")}
    >
      <p className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-text-tertiary">
        {title} · {count}
      </p>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <p className="rounded-chip border border-dashed border-hairline px-3 py-4 text-center text-[12px] text-text-tertiary">
      {text}
    </p>
  );
}
