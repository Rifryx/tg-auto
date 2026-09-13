import { Users } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ScreenHeader } from "../app/layout/AppLayout";

export function AccountsScreen() {
  return (
    <>
      <ScreenHeader title="Аккаунты" />
      <EmptyState
        icon={Users}
        title="Пока нет аккаунтов"
        hint="Подключите Telegram-аккаунт, чтобы начать прогрев."
      />
    </>
  );
}
