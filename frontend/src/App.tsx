import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./app/layout/AppLayout";
import { AccountDetailScreen } from "./screens/accounts/AccountDetailScreen";
import { AccountsListScreen } from "./screens/accounts/AccountsListScreen";
import { NewAccountFlow } from "./screens/accounts/NewAccountFlow";
import { HomeScreen } from "./screens/HomeScreen";
import { MoreScreen } from "./screens/MoreScreen";
import { TasksScreen } from "./screens/TasksScreen";

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomeScreen />} />
        <Route path="/accounts" element={<AccountsListScreen />} />
        <Route path="/accounts/new" element={<NewAccountFlow />} />
        <Route path="/accounts/:id" element={<AccountDetailScreen />} />
        <Route path="/tasks" element={<TasksScreen />} />
        <Route path="/more" element={<MoreScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
