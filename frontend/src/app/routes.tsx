import { Navigate, useLocation } from "react-router-dom";
import type { RoleName } from "../api/types";
import { useAuth } from "../auth/useAuth";
import { LoadingState } from "../components/feedback";

/** Gate that requires an authenticated session; bounces to /login otherwise,
 *  remembering where the user was headed. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingState label="Restoring session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}

/** Gate that additionally requires one of the given roles. */
export function RequireRole({
  roles,
  children,
}: {
  roles: RoleName[];
  children: React.ReactNode;
}) {
  const { hasRole } = useAuth();
  if (!hasRole(...roles)) return <Navigate to="/403" replace />;
  return <>{children}</>;
}
