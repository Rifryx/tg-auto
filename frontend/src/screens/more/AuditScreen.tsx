import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { dashboardApi } from "../dashboard/api";
import { ActivityRow } from "../dashboard/components/cards";
import { BackHeader } from "./PersonasScreen";

/* Аудит — общий лог активности (тот же источник и вёрстка, что на главной). */
export function AuditScreen() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: dashboardApi.get });

  return (
    <div className="pb-6 pt-1">
      <BackHeader title="Аудит" onBack={() => navigate("/more")} />
      {isLoading && <div className="card h-64 animate-pulse bg-surface-2" />}
      {data &&
        (data.recent_activity.length > 0 ? (
          <div className="card px-4 py-1">
            {data.recent_activity.map((item, i) => (
              <div key={i} className={i > 0 ? "border-t border-hairline" : ""}>
                <ActivityRow item={item} />
              </div>
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">Событий пока нет.</p>
        ))}
    </div>
  );
}
