import { LayoutDashboard } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { ScreenHeader } from "../app/layout/AppLayout";

export function HomeScreen() {
  return (
    <>
      <ScreenHeader title="Главная" action={<ConnectionStatus />} />
      <EmptyState
        icon={LayoutDashboard}
        title="Здесь появится сводка"
        hint="Подключите первый аккаунт — увидите статусы, алерты и активность модулей."
      />
    </>
  );
}
