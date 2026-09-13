import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./app/layout/AppLayout";
import { AccountsScreen } from "./screens/AccountsScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { MoreScreen } from "./screens/MoreScreen";
import { TasksScreen } from "./screens/TasksScreen";

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomeScreen />} />
        <Route path="/accounts" element={<AccountsScreen />} />
        <Route path="/tasks" element={<TasksScreen />} />
        <Route path="/more" element={<MoreScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
