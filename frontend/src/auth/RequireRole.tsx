import { Navigate, Outlet, useLocation } from "react-router-dom";
import { Spinner } from "../components/ui";
import { homeFor, useAuth } from "./AuthContext";

/** Only lets signed-in users with the right role through; everyone else is redirected. */
export function RequireRole({ role }: { role: "candidate" | "recruiter" }) {
  const { status, user } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Spinner label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.role !== role) return <Navigate to={homeFor(user.role)} replace />;
  return <Outlet />;
}

/** Any signed-in user (used by pages both roles share). */
export function RequireUser() {
  const { status, user } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Spinner label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
