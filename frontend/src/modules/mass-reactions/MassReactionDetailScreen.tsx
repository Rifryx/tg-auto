import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pause, Play, Square } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { Select } from "../../shared/Select";
import { massReactionsApi } from "./api";
import { CHAT_STATE_LABEL, STATUS_LABEL, STATUS_TONE } from "./labels";
import type { ChatNotifyMode, MassReactionCampaign } from "./types";

export function MassReactionDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const cid = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: campaign } = useQuery({
    queryKey: ["mass-reactions", "campaign", cid],
    queryFn: () => massReactionsApi.get(cid),
    refetchInterval: 15_000,
  });
  const chats = useQuery({
    queryKey: ["mass-reactions", "chats", cid],
    queryFn: () => massReactionsApi.listChats(cid),
  });
  const stats = useQuery({
    queryKey: ["mass-reactions", "stats", cid],
    queryFn: () => massReactionsApi.logsStats(cid),
    refetchInterval: 15_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["mass-reactions", "campaign", cid] });
    qc.invalidateQueries({ queryKey: ["mass-reactions", "chats", cid] });
  };
  const lifecycle = useMutation({
    mutationFn: (action: "start" | "pause" | "stop") => massReactionsApi[action](cid),
    onSuccess: invalidate,
  });

  if (!campaign) {
    return (
      <>
        <ScreenHeader title="Кампания" />
        <div className="card h-24 animate-pulse bg-surface-2" />
      </>
    );
  }

  return (
    <div className="pb-6">
      <button
        onClick={() => navigate("/modules/mass-reactions")}
        className="mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
        aria-label="Назад"
      >
        <ArrowLeft className="h-5 w-5" strokeWidth={1.8} aria-hidden />
      </button>

      <div className="mb-5 flex items-center gap-2.5">
        <span className={`h-2.5 w-2.5 rounded-full ${STATUS_TONE[campaign.status]}`} aria-hidden />
        <h1 className="text-[24px] font-semibold leading-tight text-text-primary" style={{ letterSpacing: "-0.02em" }}>
          {campaign.name}
        </h1>
      </div>

      <LifecycleBar campaign={campaign} onAction={(a) => lifecycle.mutate(a)} busy={lifecycle.isPending} />

      {/* Сводка параметров */}
      <div className="card mt-4 grid grid-cols-3 gap-2 p-4">
        <Metric label="Статус" value={STATUS_LABEL[campaign.status]} />
        <Metric label="Каждое N-е" value={String(campaign.every_n_message)} />
        <Metric label="Вероятность" value={`${campaign.probability_percent}%`} />
      </div>

      {/* Статистика по исходам */}
      {stats.data && Object.keys(stats.data).length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-[17px] font-semibold text-text-primary">Статистика</h2>
          <div className="card flex flex-wrap gap-x-6 gap-y-2 p-4">
            {Object.entries(stats.data).map(([k, v]) => (
              <Metric key={k} label={k} value={String(v)} />
            ))}
          </div>
        </section>
      )}

      {/* Чаты */}
      <section className="mt-6">
        <h2 className="mb-3 text-[17px] font-semibold text-text-primary">Чаты</h2>
        <AddChats campaignId={cid} onAdded={invalidate} />
        {chats.data && chats.data.length > 0 ? (
          <div className="card mt-3 overflow-hidden p-0">
            {chats.data.map((c, i) => (
              <div key={c.id} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? "border-t border-hairline" : ""}`}>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] text-text-primary">{c.title || c.chat_ref}</p>
                  <p className="truncate text-[12px] text-text-tertiary">{CHAT_STATE_LABEL[c.state]}</p>
                </div>
                <span className="shrink-0 text-[12px] tabular-nums text-text-tertiary">{c.reactions_total} реакц.</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 px-1 text-[13px] text-text-tertiary">Чаты ещё не добавлены.</p>
        )}
      </section>
    </div>
  );
}

function LifecycleBar({
  campaign,
  onAction,
  busy,
}: {
  campaign: MassReactionCampaign;
  onAction: (a: "start" | "pause" | "stop") => void;
  busy: boolean;
}) {
  const s = campaign.status;
  const btn = "flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-pill text-[14px] font-semibold disabled:opacity-40";
  return (
    <div className="flex gap-2">
      {s !== "running" && (
        <button disabled={busy} onClick={() => onAction("start")} className={`${btn} bg-accent text-accent-on active:opacity-80`}>
          <Play className="h-4 w-4" strokeWidth={2} aria-hidden /> Запустить
        </button>
      )}
      {s === "running" && (
        <button disabled={busy} onClick={() => onAction("pause")} className={`${btn} border border-hairline bg-surface-2 text-text-primary active:opacity-80`}>
          <Pause className="h-4 w-4" strokeWidth={2} aria-hidden /> Пауза
        </button>
      )}
      {(s === "running" || s === "paused") && (
        <button disabled={busy} onClick={() => onAction("stop")} className={`${btn} border border-hairline bg-surface-2 text-status-critical active:opacity-80`}>
          <Square className="h-4 w-4" strokeWidth={2} aria-hidden /> Стоп
        </button>
      )}
    </div>
  );
}

function AddChats({ campaignId, onAdded }: { campaignId: number; onAdded: () => void }) {
  const [text, setText] = useState("");
  const [notify, setNotify] = useState<ChatNotifyMode>("notify_only");
  const add = useMutation({
    mutationFn: () => massReactionsApi.addChats(campaignId, text, notify),
    onSuccess: () => {
      setText("");
      onAdded();
    },
  });
  return (
    <div className="card flex flex-col gap-3 p-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="@chat1, @chat2 или ссылки t.me/… по одному в строке"
        className="w-full resize-none rounded-chip border border-hairline bg-surface-2 px-3.5 py-2.5 text-[14px] text-text-primary outline-none focus:border-strong"
      />
      <label className="flex items-center justify-between gap-3 text-[13px] text-text-secondary">
        <span>Если чата нет в подписках аккаунта</span>
      </label>
      <Select
        value={notify}
        onChange={(v) => setNotify(v as ChatNotifyMode)}
        options={[
          { value: "notify_only", label: "Только оповестить" },
          { value: "notify_and_join", label: "Оповестить и подписаться" },
        ]}
      />
      <button
        type="button"
        disabled={!text.trim() || add.isPending}
        onClick={() => add.mutate()}
        className="min-h-[44px] rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
      >
        {add.isPending ? "Добавляю…" : "Добавить чаты"}
      </button>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[18px] font-semibold tabular-nums text-text-primary">{value}</p>
      <p className="mt-0.5 text-[11px] text-text-tertiary">{label}</p>
    </div>
  );
}
