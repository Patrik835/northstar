import type { ReactNode } from "react";
import { AdminPage } from "./features/admin/AdminPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { AuthProvider } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RegisterPage } from "./features/auth/RegisterPage";
import { RegistrationPendingPage } from "./features/auth/RegistrationPendingPage";
import { VerifyEmailPage } from "./features/auth/VerifyEmailPage";
import { ChatPage } from "./features/chat/ChatPage";
import { ConnectionsPage } from "./features/connections/ConnectionsPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { HoldingsPage } from "./features/holdings/HoldingsPage";
import { ProfilePage } from "./features/profile/ProfilePage";
import { AppLayout } from "./layouts/AppLayout";
import { RouterProvider, useRouter } from "./routing/Router";

const pages: Record<string, ReactNode> = {
  "/": <DashboardPage />,
  "/holdings": <HoldingsPage />,
  "/activity": <ActivityPage />,
  "/connections": <ConnectionsPage />,
  "/assistant": <ChatPage />,
  "/profile": <ProfilePage />,
  "/admin": <AdminPage />,
};

function AppRoutes() {
  const { path } = useRouter();
  if (path === "/login") return <LoginPage />;
  if (path === "/register") return <RegisterPage />;
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
