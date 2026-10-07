import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./app/layout/AppLayout";
import { AccountDetailScreen } from "./screens/accounts/AccountDetailScreen";
import { AccountsListScreen } from "./screens/accounts/AccountsListScreen";
import { BulkImportScreen } from "./screens/accounts/BulkImportScreen";
import { NewAccountFlow } from "./screens/accounts/NewAccountFlow";
import { DashboardScreen } from "./screens/dashboard/DashboardScreen";
import { AboutScreen } from "./screens/more/AboutScreen";
import { AuditScreen } from "./screens/more/AuditScreen";
import { AutopilotScreen } from "./screens/more/AutopilotScreen";
import { MoreScreen } from "./screens/more/MoreScreen";
import { ServicesScreen } from "./screens/services/ServicesScreen";
import { PersonasScreen } from "./screens/more/PersonasScreen";
import { ProjectsScreen } from "./screens/more/ProjectsScreen";
import { ProfileAssetsScreen } from "./screens/more/ProfileAssetsScreen";
import { ProxiesScreen } from "./screens/more/ProxiesScreen";
import { SettingsScreen } from "./screens/more/SettingsScreen";
import { CampaignDetailScreen } from "./modules/commenting/CampaignDetailScreen";
import { CampaignsScreen } from "./modules/commenting/CampaignsScreen";
import { NewCampaignScreen } from "./modules/commenting/NewCampaignScreen";
import { ShillingListScreen } from "./modules/shilling/ShillingListScreen";
import { NewShillingWizard } from "./modules/shilling/NewShillingWizard";
import { ShillingDetailScreen } from "./modules/shilling/ShillingDetailScreen";
import { PrimingListScreen } from "./modules/priming/PrimingListScreen";
import { NewPrimingScreen } from "./modules/priming/NewPrimingScreen";
import { PrimingDetailScreen } from "./modules/priming/PrimingDetailScreen";
import { PrimingCampaignRun } from "./modules/priming/PrimingCampaignRun";
import { PrimingCampaignLogs } from "./modules/priming/PrimingCampaignLogs";
import { ParsingListsScreen } from "./modules/parsing/ParsingListsScreen";
import { CommunitiesScreen } from "./modules/parsing/CommunitiesScreen";
import { DiscoverScreen } from "./modules/parsing/DiscoverScreen";
import { CommunityListScreen } from "./modules/parsing/CommunityListScreen";
import { ListOpsScreen } from "./modules/parsing/ListOpsScreen";
import { RunParsingScreen } from "./modules/parsing/RunParsingScreen";
import { AdminScreen } from "./screens/admin/AdminScreen";
import { BillingScreen } from "./screens/billing/BillingScreen";

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<DashboardScreen />} />
        <Route path="/accounts" element={<AccountsListScreen />} />
        <Route path="/accounts/new" element={<NewAccountFlow />} />
        <Route path="/accounts/import-bulk" element={<BulkImportScreen />} />
        <Route path="/accounts/:id" element={<AccountDetailScreen />} />
        {/* «Задачи» = модули; сейчас единственный модуль — commenting (§9 брифа). */}
        <Route path="/tasks" element={<CampaignsScreen />} />
        <Route path="/modules/commenting" element={<CampaignsScreen />} />
        <Route path="/modules/commenting/campaigns/new" element={<NewCampaignScreen />} />
        <Route path="/modules/commenting/campaigns/:id" element={<CampaignDetailScreen />} />
        <Route path="/modules/shilling" element={<ShillingListScreen />} />
        <Route path="/modules/shilling/campaigns/new" element={<NewShillingWizard />} />
        <Route path="/modules/shilling/campaigns/:id" element={<ShillingDetailScreen />} />
        <Route path="/modules/priming" element={<PrimingListScreen />} />
        <Route path="/modules/priming/campaigns/new" element={<NewPrimingScreen />} />
        <Route path="/modules/priming/campaigns/:id" element={<PrimingDetailScreen />} />
        <Route path="/modules/priming/campaigns/:id/run" element={<PrimingCampaignRun />} />
        <Route path="/modules/priming/campaigns/:id/logs" element={<PrimingCampaignLogs />} />
        <Route path="/modules/parsing" element={<ParsingListsScreen />} />
        <Route path="/modules/parsing/run" element={<RunParsingScreen />} />
        <Route path="/modules/parsing/ops" element={<ListOpsScreen />} />
        <Route path="/modules/parsing/communities" element={<CommunitiesScreen />} />
        <Route path="/modules/parsing/discover" element={<DiscoverScreen />} />
        <Route path="/modules/parsing/lists/:id/communities" element={<CommunityListScreen />} />
        <Route path="/services" element={<ServicesScreen />} />
        <Route path="/more" element={<MoreScreen />} />
        <Route path="/more/personas" element={<PersonasScreen />} />
        <Route path="/more/projects" element={<ProjectsScreen />} />
        <Route path="/more/proxies" element={<ProxiesScreen />} />
        <Route path="/more/profile-assets" element={<ProfileAssetsScreen />} />
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
