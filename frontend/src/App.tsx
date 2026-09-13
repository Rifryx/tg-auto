import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./app/layout/AppLayout";
import { AccountDetailScreen } from "./screens/accounts/AccountDetailScreen";
import { AccountsListScreen } from "./screens/accounts/AccountsListScreen";
import { NewAccountFlow } from "./screens/accounts/NewAccountFlow";
import { HomeScreen } from "./screens/HomeScreen";
import { MoreScreen } from "./screens/MoreScreen";
import { CampaignDetailScreen } from "./modules/commenting/CampaignDetailScreen";
import { CampaignsScreen } from "./modules/commenting/CampaignsScreen";
import { NewCampaignScreen } from "./modules/commenting/NewCampaignScreen";

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomeScreen />} />
        <Route path="/accounts" element={<AccountsListScreen />} />
        <Route path="/accounts/new" element={<NewAccountFlow />} />
        <Route path="/accounts/:id" element={<AccountDetailScreen />} />
        {/* «Задачи» = модули; сейчас единственный модуль — commenting (§9 брифа). */}
        <Route path="/tasks" element={<CampaignsScreen />} />
        <Route path="/modules/commenting" element={<CampaignsScreen />} />
        <Route path="/modules/commenting/campaigns/new" element={<NewCampaignScreen />} />
        <Route path="/modules/commenting/campaigns/:id" element={<CampaignDetailScreen />} />
        <Route path="/more" element={<MoreScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
