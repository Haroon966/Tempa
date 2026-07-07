import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function PanelCard({
  title,
  description,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
  headerClassName,
  descriptionClassName,
  titleClassName,
}: {
  title: string
  description?: string
  icon?: LucideIcon
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
  contentClassName?: string
  headerClassName?: string
  descriptionClassName?: string
  titleClassName?: string
}) {
  return (
    <Card className={cn("surface-card min-h-0 overflow-hidden ring-0 shadow-none", className)}>
      <CardHeader className={cn("pb-4", headerClassName)}>
        <div className="flex items-start justify-between gap-2 sm:gap-3">
          <div className="flex min-w-0 items-start gap-2.5 sm:gap-3">
            {Icon && (
              <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-border bg-muted text-primary sm:size-10">
                <Icon className="size-4" aria-hidden />
              </div>
            )}
            <div className="min-w-0">
              <CardTitle
                className={cn(
                  "text-sm font-bold tracking-tight text-foreground",
                  titleClassName,
                )}
              >
                {title}
              </CardTitle>
              {description && (
                <CardDescription
                  className={cn(
                    "mt-0.5 text-xs leading-relaxed text-muted-foreground",
                    descriptionClassName,
                  )}
                >
                  {description}
                </CardDescription>
              )}
            </div>
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      </CardHeader>
      <CardContent className={contentClassName}>{children}</CardContent>
    </Card>
  )
}
