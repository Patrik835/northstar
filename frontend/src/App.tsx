import type { ReactNode } from "react";
import { AdminPage } from "./features/admin/AdminPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { AnalyticsPage } from "./features/analytics/AnalyticsPage";
import { AuthProvider } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { ForgotPasswordPage } from "./features/auth/ForgotPasswordPage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RegisterPage } from "./features/auth/RegisterPage";
import { ResetPasswordPage } from "./features/auth/ResetPasswordPage";
import { RegistrationPendingPage } from "./features/auth/RegistrationPendingPage";
import { VerifyEmailPage } from "./features/auth/VerifyEmailPage";
import { ChatPage } from "./features/chat/ChatPage";
import { ConnectionsPage } from "./features/connections/ConnectionsPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { HoldingsPage } from "./features/holdings/HoldingsPage";
import { ProfilePage } from "./features/profile/ProfilePage";
import { UpdatesPage } from "./features/updates/UpdatesPage";
import { AppLayout } from "./layouts/AppLayout";
import { RouterProvider, useRouter } from "./routing/Router";

const pages: Record<string, ReactNode> = {
  "/": <DashboardPage />,
  "/holdings": <HoldingsPage />,
  "/activity": <ActivityPage />,
  "/analytics": <AnalyticsPage />,
  "/connections": <ConnectionsPage />,
  "/updates": <UpdatesPage />,
  "/assistant": <ChatPage />,
  "/profile": <ProfilePage />,
  "/admin": <AdminPage />,
};

function AppRoutes() {
  const { path } = useRouter();
  if (path === "/login") return <LoginPage />;
  if (path === "/register") return <RegisterPage />;
  if (path === "/forgot-password") return <ForgotPasswordPage />;
  if (path === "/reset-password") return <ResetPasswordPage />;
  if (path === "/registration-pending") return <RegistrationPendingPage />;
  if (path === "/verify-email") return <VerifyEmailPage />;
  return (
    <ProtectedRoute>
      <AppLayout>{pages[path] ?? <DashboardPage />}</AppLayout>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <RouterProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </RouterProvider>
  );
}
