import { useEffect, type ReactNode } from "react";
import { useRouter } from "../../routing/Router";
import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const { navigate } = useRouter();
  useEffect(() => {
    if (!loading && !user) navigate("/login", true);
  }, [loading, navigate, user]);
  if (loading) return <div className="centered">Loading your portfolio…</div>;
  return user ? children : null;
}
