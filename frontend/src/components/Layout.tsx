import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { NAV } from "../nav";
import { Button } from "./ui";

export function Layout() {
  const { user, logout } = useAuth();
  const links = user ? NAV[user.role] : [];

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="text-lg font-bold text-indigo-800">
            HireSense <span className="text-slate-900">AI</span>
          </Link>
          <nav aria-label="Main" className="flex flex-wrap items-center gap-1">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === "/recruiter"}
                className={({ isActive }) =>
                  `rounded-md px-3 py-2 text-sm font-medium ${isActive ? "bg-indigo-100 text-indigo-900" : "text-slate-700 hover:bg-slate-100"}`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          {user && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-slate-700">
                {user.full_name} <span className="text-slate-500">({user.role})</span>
              </span>
              <Button tone="secondary" onClick={logout}>
                Sign out
              </Button>
            </div>
          )}
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8 focus:outline-none">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-slate-500">
        AI features in HireSense are advisory. A person makes every hiring decision.
      </footer>
    </div>
  );
}
