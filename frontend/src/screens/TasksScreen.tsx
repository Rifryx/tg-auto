import { LayoutGrid } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ScreenHeader } from "../app/layout/AppLayout";

export function TasksScreen() {
  return (
    <>
      <ScreenHeader title="Задачи" />
      <EmptyState
        icon={LayoutGrid}
        title="Нет активных модулей"
        hint="Создайте кампанию — она появится здесь карточкой."
      />
    </>
  );
}
