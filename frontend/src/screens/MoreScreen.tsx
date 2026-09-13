import { Settings } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ScreenHeader } from "../app/layout/AppLayout";

export function MoreScreen() {
  return (
    <>
      <ScreenHeader title="Ещё" />
      <EmptyState
        icon={Settings}
        title="Настройки скоро"
        hint="Профиль, прокси и параметры прогрева появятся здесь."
      />
    </>
  );
}
