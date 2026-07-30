import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { RequireAuth, RequireRole } from "./routes";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
import { ForgotPasswordPage } from "../pages/ForgotPasswordPage";
import { ResetPasswordPage } from "../pages/ResetPasswordPage";
import { ProfilePage } from "../pages/ProfilePage";
import { DevicesPage } from "../pages/DevicesPage";
import { DeviceDetailPage } from "../pages/DeviceDetailPage";
import { CrashesPage } from "../pages/CrashesPage";
import { CrashDetailPage } from "../pages/CrashDetailPage";
import { GroupsPage } from "../pages/GroupsPage";
import { GroupDetailPage } from "../pages/GroupDetailPage";
import { KnowledgeBasePage } from "../pages/KnowledgeBasePage";
import { UsersPage } from "../pages/UsersPage";
import { NotFoundPage, ForbiddenPage } from "../pages/StatusPages";

export function App() {
  return (
    <Routes>
      {/* Public auth routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />

      {/* Authenticated app */}
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/devices" replace />} />
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/devices/:id" element={<DeviceDetailPage />} />
        <Route path="/crashes" element={<CrashesPage />} />
        <Route path="/crashes/:id" element={<CrashDetailPage />} />
        <Route path="/groups" element={<GroupsPage />} />
        <Route path="/groups/:id" element={<GroupDetailPage />} />
        <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
        <Route
          path="/users"
          element={
            <RequireRole roles={["admin"]}>
              <UsersPage />
            </RequireRole>
          }
        />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/403" element={<ForbiddenPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
