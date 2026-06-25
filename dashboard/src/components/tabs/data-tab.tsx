import { useState } from "react"
import {
  ArchiveIcon,
  ArrowRightIcon,
  CalendarIcon,
  DatabaseIcon,
  HardDriveIcon,
  MessageCircleIcon,
} from "lucide-react"
import type { DashboardPayload, MeetingRecord } from "@/types/dashboard"
import { MeetingDetailPanel } from "@/components/meeting-detail-panel"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { formatBytes, formatTime } from "@/lib/format"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatCard } from "@/components/dashboard/stat-card"
import { StatusBadge } from "@/components/status-badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

export function DataTab({ data }: { data: DashboardPayload }) {
  const navigateSection = useNavigateSection()
  const { data: stats, meetings, calendar, whatsapp } = data
  const [selectedMeeting, setSelectedMeeting] = useState<MeetingRecord | null>(null)

  const rag = data.connections.rag

  return (
    <div className="flex flex-col gap-8">
      {rag?.error != null && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/8 p-4 text-sm text-destructive">
          RAG store error: {String(rag.error)}
        </div>
      )}
      <section className="grid gap-4 sm:grid-cols-2">
        <StatCard
          label="Memory index"
          value={stats.rag_chunks}
          hint={`${stats.meetings_count} meeting archives`}
          icon={DatabaseIcon}
        />
        <StatCard
          label="Vector store"
          value={formatBytes(stats.vector_db_bytes)}
          hint={stats.vector_db_path}
          icon={HardDriveIcon}
        />
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <PanelCard title="Storage paths" description="On-disk data locations" icon={HardDriveIcon}>
          <dl className="flex flex-col gap-2">
            {[
              { label: "Vector DB", size: formatBytes(stats.vector_db_bytes), path: stats.vector_db_path },
              { label: "Meetings",  size: formatBytes(stats.meetings_bytes),  path: stats.meetings_path },
              { label: "Sessions",  size: null,                                path: stats.sessions_path },
              { label: "SQLite DB", size: null,                                path: stats.db_path },
            ].map(({ label, size, path }) => (
              <div key={label} className="list-row">
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
                    {label}
                  </dt>
                  {size && (
                    <Badge variant="outline" className="border-border bg-muted text-xs text-primary">
                      {size}
                    </Badge>
                  )}
                </div>
                <dd className="mt-1 truncate text-xs text-muted-foreground">{path}</dd>
              </div>
            ))}
            <div className="flex items-center justify-between rounded-lg border border-border bg-muted/30 p-3">
              <span className="text-sm text-foreground">Playwright CLI</span>
              <StatusBadge status={stats.playwright_installed ? "healthy" : "unhealthy"} />
            </div>
          </dl>
        </PanelCard>

        <PanelCard
          title="Meeting archives"
          description={`${meetings.length} recorded sessions`}
          icon={ArchiveIcon}
        >
          {meetings.length === 0 ? (
            <p className="text-sm text-muted-foreground">No meetings archived yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border/60 hover:bg-transparent">
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Title</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Started</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Artifacts</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Link</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {meetings.slice(0, 8).map((m) => (
                  <TableRow
                    key={m.id}
                    className="cursor-pointer border-border/40 transition-colors hover:bg-muted/40"
                    onClick={() => setSelectedMeeting(m)}
                  >
                    <TableCell className="font-medium text-foreground">{m.title || m.id}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {m.started_at ? formatTime(m.started_at) : "—"}
                    </TableCell>
                    <TableCell>
                      {m.artifacts ? (
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(m.artifacts).map(([k, ok]) =>
                            ok ? (
                              <Badge key={k} variant="outline" className="text-[10px]">
                                {k}
                              </Badge>
                            ) : null,
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {m.meet_link ? (
                        <a
                          href={m.meet_link}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex cursor-pointer items-center gap-1 text-xs text-primary transition-colors hover:underline"
                        >
                          Open <ArrowRightIcon className="size-3" />
                        </a>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </PanelCard>

        {selectedMeeting && (
          <PanelCard title="Meeting detail" description={selectedMeeting.title || selectedMeeting.id}>
            <MeetingDetailPanel meeting={selectedMeeting} onClose={() => setSelectedMeeting(null)} />
          </PanelCard>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PanelCard title="Upcoming calendar" description="Next 7 days" icon={CalendarIcon}>
          {calendar.upcoming.length === 0 ? (
            <p className="text-sm text-muted-foreground">No upcoming events.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border/60 hover:bg-transparent">
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Event</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-muted-foreground/70">Meet</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {calendar.upcoming.slice(0, 10).map((ev) => (
                  <TableRow key={ev.id} className="border-border/40 transition-colors hover:bg-muted/40">
                    <TableCell>
                      <div className="font-medium text-foreground">{ev.summary}</div>
                      <div className="text-xs text-muted-foreground">{formatTime(ev.start)}</div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={ev.has_meet ? "healthy" : "degraded"} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </PanelCard>

        <PanelCard
          title="Recent WhatsApp"
          description="Inbound message buffer"
          icon={MessageCircleIcon}
        >
          {whatsapp.recent_messages.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <MessageCircleIcon className="size-7 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">No messages received yet.</p>
              <button
                type="button"
                onClick={() => navigateSection("connections")}
                className="inline-flex cursor-pointer items-center gap-1 text-xs text-primary/70 transition-colors hover:text-primary"
              >
                Configure WhatsApp <ArrowRightIcon className="size-3" />
              </button>
            </div>
          ) : (
            <ul className="flex max-h-80 flex-col gap-2 overflow-auto pr-1">
              {whatsapp.recent_messages.map((msg) => (
                <li key={msg.id} className="list-row">
                  <span className="text-sm font-medium text-foreground">{msg.from}</span>
                  <p className="mt-1 text-xs text-muted-foreground">{msg.text}</p>
                </li>
              ))}
            </ul>
          )}
        </PanelCard>
      </div>
    </div>
  )
}
