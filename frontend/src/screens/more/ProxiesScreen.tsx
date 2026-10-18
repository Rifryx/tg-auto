import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { maskHost } from "../../shared/format";
import { LimitBanner } from "../../shared/LimitBanner";
import { useLimit } from "../../shared/limits";
import type { ProxyType } from "../../shared/types";
import type { ProxyOccupancy } from "./api";
import {
  CapsuleButton,
  ConfirmDialog,
  Field,
  Section,
  SegmentedControl,
  TextInput,
} from "../../modules/commenting/components/ui";
import { proxiesApi } from "./api";
import { BackHeader } from "./PersonasScreen";
import { Toast } from "./components/ui";

const TYPE_OPTIONS: { value: ProxyType; label: string }[] = [
  { value: "socks5", label: "SOCKS5" },
  { value: "http", label: "HTTP" },
];

const PROXY_DOT: Record<ProxyOccupancy["status"], string> = {
  alive: "bg-status-active",
  dead: "bg-status-critical",
  unchecked: "bg-status-neutral",
};
const PROXY_LABEL: Record<ProxyOccupancy["status"], string> = {
  alive: "жив",
  dead: "мёртв",
  unchecked: "не пров.",
};

export function ProxiesScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [host, setHost] = useState("");
  const [port, setPort] = useState("1080");
  const [type, setType] = useState<ProxyType>("socks5");
  const [geo, setGeo] = useState("");
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [toDelete, setToDelete] = useState<ProxyOccupancy | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Пул (этап 3, backlog #2): вместе с проксями получаем занятость по
  // аккаунтам, чтобы отличать «свободен» от «привязан к #N».
  const list = useQuery({ queryKey: ["proxy-pool"], queryFn: proxiesApi.pool });

  const create = useMutation({
    mutationFn: () =>
      proxiesApi.create({
        host: host.trim(),
        port: Number(port),
        type,
        name: name.trim() || null,
        geo: geo.trim() || null,
      }),
    onSuccess: () => {
      setHost("");
      setGeo("");
      setName("");
      qc.invalidateQueries({ queryKey: ["proxy-pool"] });
      qc.invalidateQueries({ queryKey: ["proxies"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => proxiesApi.remove(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["proxy-pool"] });
      qc.invalidateQueries({ queryKey: ["proxies"] });
    },
  });
  const checkAll = useMutation({
    mutationFn: proxiesApi.checkAll,
    onSuccess: () => setToast("Проверка прокси поставлена"),
  });

  const valid = host.trim() !== "" && Number(port) > 0;
  const limit = useLimit("proxies_max");
  const blocked = limit?.atLimit ?? false;

  // Поиск по названию/хосту/гео — чтобы быстро найти прокси в длинном списке.
  const q = search.trim().toLowerCase();
  const all = list.data ?? [];
  const items = q
    ? all.filter(
        (p) =>
          (p.name ?? "").toLowerCase().includes(q) ||
          p.host.toLowerCase().includes(q) ||
          (p.geo ?? "").toLowerCase().includes(q),
      )
    : all;

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Прокси" onBack={() => navigate("/more")} />

      <Section
        title={`Все (${list.data?.length ?? 0})`}
        action={
          <button
            onClick={() => checkAll.mutate()}
            disabled={checkAll.isPending || !(list.data && list.data.length)}
            className="rounded-pill border border-hairline bg-surface-2 px-3 py-1.5 text-[13px] text-text-primary disabled:opacity-50"
          >
            {checkAll.isPending ? "Ставим…" : "Проверить всё"}
          </button>
        }
      >
        {all.length > 0 && (
          <div className="mb-3">
            <TextInput
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию, хосту или гео"
            />
          </div>
        )}
        {all.length > 0 ? (
          items.length > 0 ? (
            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-3">
              {items.map((p) => (
              <div key={p.id} className="card flex items-center gap-3 px-4 py-3">
                <span className={`h-2 w-2 shrink-0 rounded-full ${PROXY_DOT[p.status]}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] text-text-primary">
                    {p.name ? (
                      p.name
                    ) : (
                      <span className="nums">
                        {maskHost(p.host)}:{p.port}
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[12px] text-text-tertiary">
                    {p.name ? (
                      <span className="nums">
                        {maskHost(p.host)}:{p.port} ·{" "}
                      </span>
                    ) : null}
                    {p.type.toUpperCase()} · {p.geo ?? "—"} · {PROXY_LABEL[p.status]}
                    {p.is_free ? " · свободен" : ` · занят #${p.assigned_account_id}`}
                  </p>
                </div>
                <button
                  onClick={() => setToDelete(p)}
                  aria-label="Удалить"
                  disabled={!p.is_free}
                  title={p.is_free ? "" : "Занят аккаунтом — сначала переназначьте прокси"}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-status-critical disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
              ))}
            </div>
          ) : (
            <p className="px-1 text-[13px] text-text-tertiary">
              Ничего не найдено по запросу «{search}».
            </p>
          )
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">Прокси пока нет.</p>
        )}
      </Section>

      <Section title="Новый прокси">
        <LimitBanner feature="proxies_max" />
        <div className="card p-4">
          <Field label="Название (опц.)">
            <TextInput
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="DE-residential-1"
              maxLength={64}
            />
          </Field>
          <div className="flex gap-2">
            <div className="flex-[2]">
              <Field label="Хост">
                <TextInput value={host} onChange={(e) => setHost(e.target.value)} placeholder="10.0.0.1" className="nums" />
              </Field>
            </div>
            <div className="flex-1">
              <Field label="Порт">
                <TextInput value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" className="nums" />
              </Field>
            </div>
          </div>
          <div className="mb-4">
            <p className="mb-1.5 px-1 text-[13px] text-text-tertiary">Тип</p>
            <SegmentedControl options={TYPE_OPTIONS} value={type} onChange={setType} />
          </div>
          <Field label="Гео (опц.)">
            <TextInput value={geo} onChange={(e) => setGeo(e.target.value)} placeholder="DE" />
          </Field>
          <CapsuleButton
            variant={!blocked && valid ? "accent" : "secondary"}
            disabled={blocked || !valid || create.isPending}
            onClick={() => {
              if (blocked) return navigate("/billing");
              create.mutate();
            }}
          >
            {blocked
              ? "Лимит достигнут"
              : create.isPending
                ? "Добавляем…"
                : "Добавить прокси"}
          </CapsuleButton>
        </div>
      </Section>

      <ConfirmDialog
        open={toDelete != null}
        title="Удалить прокси?"
        message={`${toDelete ? maskHost(toDelete.host) : ""} будет удалён.`}
        confirmLabel="Удалить"
        danger
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
      <Toast message={toast} onDone={() => setToast(null)} />
    </div>
  );
}
