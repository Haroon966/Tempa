import { NavLink, Outlet, useLocation, Navigate } from "react-router-dom"
import { BotIcon, RouteIcon } from "lucide-react"
import { cn } from "@/lib/utils"

const SUB_TABS = [
  { path: "/diagnostics/components", label: "Components", icon: BotIcon },
  { path: "/diagnostics/flows", label: "E2E Flows", icon: RouteIcon },
] as const

export function DiagnosticsTab() {
  const { pathname } = useLocation()
  const isSubRoute = SUB_TABS.some((t) => t.path === pathname)
  if (!isSubRoute) return <Navigate to="/diagnostics/components" replace />

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5">
      <nav className="flex gap-1 rounded-lg border border-border bg-muted p-1 w-fit" aria-label="Diagnostics sections">
        {SUB_TABS.map(({ path, label, icon: Icon }) => {
          const active = pathname === path
          return (
            <NavLink
              key={path}
              to={path}
              className={cn(
                "flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-200",
                active
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          )
        })}
      </nav>
      <Outlet />
    </div>
  )
}
