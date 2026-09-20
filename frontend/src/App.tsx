import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./app/layout/AppLayout";
import { AccountDetailScreen } from "./screens/accounts/AccountDetailScreen";
import { AccountsListScreen } from "./screens/accounts/AccountsListScreen";
import { NewAccountFlow } from "./screens/accounts/NewAccountFlow";
import { DashboardScreen } from "./screens/dashboard/DashboardScreen";
import { AboutScreen } from "./screens/more/AboutScreen";
import { AuditScreen } from "./screens/more/AuditScreen";
import { AutopilotScreen } from "./screens/more/AutopilotScreen";
import { MoreScreen } from "./screens/more/MoreScreen";
import { PersonasScreen } from "./screens/more/PersonasScreen";
import { ProjectsScreen } from "./screens/more/ProjectsScreen";
import { ProxiesScreen } from "./screens/more/ProxiesScreen";
import { SettingsScreen } from "./screens/more/SettingsScreen";
import { CampaignDetailScreen } from "./modules/commenting/CampaignDetailScreen";
import { CampaignsScreen } from "./modules/commenting/CampaignsScreen";
import { NewCampaignScreen } from "./modules/commenting/NewCampaignScreen";
import { AdminScreen } from "./screens/admin/AdminScreen";
import { BillingScreen } from "./screens/billing/BillingScreen";

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<DashboardScreen />} />
        <Route path="/accounts" element={<AccountsListScreen />} />
        <Route path="/accounts/new" element={<NewAccountFlow />} />
        <Route path="/accounts/:id" element={<AccountDetailScreen />} />
        {/* «Задачи» = модули; сейчас единственный модуль — commenting (§9 брифа). */}
        <Route path="/tasks" element={<CampaignsScreen />} />
        <Route path="/modules/commenting" element={<CampaignsScreen />} />
        <Route path="/modules/commenting/campaigns/new" element={<NewCampaignScreen />} />
        <Route path="/modules/commenting/campaigns/:id" element={<CampaignDetailScreen />} />
        <Route path="/more" element={<MoreScreen />} />
        <Route path="/more/personas" element={<PersonasScreen />} />
        <Route path="/more/projects" element={<ProjectsScreen />} />
        <Route path="/more/proxies" element={<ProxiesScreen />} />
        <Route path="/more/audit" element={<AuditScreen />} />
        <Route path="/more/autopilot" element={<AutopilotScreen />} />
        <Route path="/more/settings" element={<SettingsScreen />} />
        <Route path="/more/about" element={<AboutScreen />} />
        <Route path="/billing" element={<BillingScreen />} />
        <Route path="/admin" element={<AdminScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
