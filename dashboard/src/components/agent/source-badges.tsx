import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { ChatSource } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type SourceBadgesProps = {
  sources: ChatSource[]
  className?: string
  alignRight?: boolean
  onNavigateData?: () => void
}

export function SourceBadges({ sources, className, alignRight, onNavigateData }: SourceBadgesProps) {
  if (!sources.length) return null

  return (
    <TooltipProvider delay={200}>
      <div className={cn("flex flex-wrap gap-1.5", alignRight && "justify-end", className)}>
        {sources.map((src, i) => {
          const label = src.label ?? src.tool ?? `Source ${i + 1}`
          const detail = src.content ?? src.source ?? src.title
          const isMemory =
            String(src.tool ?? label).includes("rag") || String(label).toLowerCase().includes("memory")

          return (
            <Tooltip key={`${label}-${i}`}>
              <TooltipTrigger
                render={
                  <Badge
                    variant="outline"
                    className={cn(
                      "max-w-full truncate text-[10px] text-muted-foreground",
                      isMemory && onNavigateData && "cursor-pointer hover:border-primary/30",
                    )}
                    onClick={isMemory && onNavigateData ? onNavigateData : undefined}
                  >
                    {label}
                  </Badge>
                }
              />
              {detail ? (
                <TooltipContent side="top" className="max-w-sm whitespace-pre-wrap">
                  {String(detail)}
                </TooltipContent>
              ) : null}
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
