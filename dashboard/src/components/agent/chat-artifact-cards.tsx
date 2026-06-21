import type { ChatArtifact } from "@/lib/api"
import { Badge } from "@/components/ui/badge"

export function ChatArtifactCards({ artifacts }: { artifacts: ChatArtifact[] }) {
  if (!artifacts.length) return null

  return (
    <div className="flex flex-col gap-2">
      {artifacts.map((artifact, i) => (
        <ArtifactCard key={`${artifact.type}-${i}`} artifact={artifact} />
      ))}
    </div>
  )
}

function ArtifactCard({ artifact }: { artifact: ChatArtifact }) {
  if (artifact.type === "gmail_search") {
    const messages = (artifact.messages as Array<Record<string, unknown>>) ?? []
    const count = Number(artifact.count ?? messages.length)
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-3 text-left text-xs">
        <div className="mb-2 flex items-center gap-2">
          <Badge variant="outline" className="text-[10px]">
            Gmail
          </Badge>
          <span className="font-medium">{count} message{count === 1 ? "" : "s"}</span>
        </div>
        <ul className="flex flex-col gap-1.5">
          {messages.slice(0, 5).map((msg, idx) => (
            <li key={String(msg.id ?? idx)} className="rounded border border-border/60 bg-card px-2 py-1.5">
              <p className="truncate font-medium">{String(msg.subject ?? "(no subject)")}</p>
              <p className="truncate text-muted-foreground">{String(msg.from ?? "")}</p>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (artifact.type === "calendar_events") {
    const upcoming = (artifact.upcoming as Array<Record<string, unknown>>) ?? []
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-3 text-left text-xs">
        <div className="mb-2 flex items-center gap-2">
          <Badge variant="outline" className="text-[10px]">
            Calendar
          </Badge>
          <span className="font-medium">{upcoming.length} upcoming</span>
        </div>
        <ul className="flex flex-col gap-1.5">
          {upcoming.slice(0, 5).map((ev, idx) => (
            <li key={`${ev.start}-${idx}`} className="rounded border border-border/60 bg-card px-2 py-1.5">
              <p className="font-medium">{String(ev.summary ?? "Event")}</p>
              <p className="text-muted-foreground">{String(ev.start ?? "").slice(0, 16)}</p>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return null
}
