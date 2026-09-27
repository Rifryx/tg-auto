import { useQuery } from "@tanstack/react-query";
import { primingApi } from "../api";

/* React-Query хук: список кампаний прайминга. Обновляется каждые 15 сек,
   как в шиллинге. */
export function useCampaigns() {
  return useQuery({
    queryKey: ["priming", "campaigns"],
    queryFn: primingApi.list,
    refetchInterval: 15_000,
  });
}
