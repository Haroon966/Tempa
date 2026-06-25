import { useCallback, useEffect, useState } from "react"
import { MailIcon, RefreshCwIcon, UserIcon } from "lucide-react"
import {
  fetchContacts,
  fetchGmailMessages,
  syncContacts,
  syncGmail,
  type Contact,
  type GmailMessage,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export function MailTab() {
  const [messages, setMessages]   = useState<GmailMessage[]>([])
  const [lastSync, setLastSync]   = useState<string>("")
  const [loading, setLoading]     = useState(true)
  const [syncing, setSyncing]             = useState(false)
  const [contactSyncing, setContactSyncing] = useState(false)
  const [contacts, setContacts]           = useState<Contact[]>([])
  const [syncError, setSyncError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const refreshContacts = useCallback(async () => {
    try {
      const data = await fetchContacts()
      setContacts(data.contacts ?? [])
    } catch { setContacts([]) }
  }, [])

  useEffect(() => { void refreshContacts() }, [refreshContacts])

  const handleContactSync = async () => {
    setContactSyncing(true)
    try { await syncContacts(); await refreshContacts() }
    finally { setContactSyncing(false) }
  }

  const refresh = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await fetchGmailMessages()
      setMessages(data.messages ?? [])
      setLastSync(data.last_sync_at ?? "")
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load mail")
      setMessages([])
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const handleSync = async () => {
    setSyncing(true)
    setSyncError(null)
    try {
      await syncGmail()
      await refresh()
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : "Sync failed")
    } finally { setSyncing(false) }
  }

  const unreadCount = messages.filter((m) => m.unread).length

  return (
    <div className="flex flex-col gap-6">
      {/* ── Inbox ────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <MailIcon className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Inbox</h2>
            {unreadCount > 0 && (
              <Badge variant="outline" className="border-border bg-muted text-xs text-primary">
                {unreadCount} unread
              </Badge>
            )}
            {lastSync && (
              <span className="text-xs text-muted-foreground/70">
                · synced {new Date(lastSync).toLocaleTimeString()}
              </span>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="cursor-pointer hover:border-primary/30"
            onClick={() => void handleSync()}
            disabled={syncing}
          >
            <RefreshCwIcon className={cn("size-3.5", syncing && "animate-spin")} />
            {syncing ? "Syncing…" : "Sync now"}
          </Button>
        </div>

        {(syncError || loadError) && (
          <p className="mb-3 text-sm text-destructive">{syncError || loadError}</p>
        )}

        {loading && messages.length === 0 ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full rounded-xl bg-muted" />
            ))}
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-muted/30 py-14 text-center">
            <MailIcon className="size-7 text-muted-foreground/30" />
            <p className="text-sm font-medium text-foreground">
              {loadError ? "Could not load inbox" : "No messages"}
            </p>
            <p className="text-xs text-muted-foreground">
              {loadError
                ? "Check Gmail connection in Connections and try Sync now."
                : "Connect Gmail and run sync to see your inbox here."}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {messages.map((m) => (
              <div
                key={m.id}
                className={cn(
                  "rounded-xl border p-4 transition-all duration-200",
                  m.unread
                    ? "border-border bg-muted hover:bg-muted/80"
                    : "border-border bg-card hover:bg-muted/40",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className={cn("truncate text-sm", m.unread ? "font-semibold text-foreground" : "font-medium text-foreground/80")}>
                        {m.subject || "(no subject)"}
                      </p>
                      {m.unread && (
                        <span
                          className="size-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_6px_rgba(61,108,185,0.8)]"
                          aria-label="Unread"
                        />
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {m.from} · {m.date}
                    </p>
                  </div>
                </div>
                {m.snippet && (
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground/80">{m.snippet}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Contacts ─────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <UserIcon className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Contacts</h2>
            {contacts.length > 0 && (
              <span className="text-xs text-muted-foreground/70">{contacts.length} synced</span>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="cursor-pointer hover:border-primary/30"
            onClick={() => void handleContactSync()}
            disabled={contactSyncing}
          >
            <RefreshCwIcon className={cn("size-3.5", contactSyncing && "animate-spin")} />
            {contactSyncing ? "Syncing…" : "Sync contacts"}
          </Button>
        </div>

        {contacts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No contacts synced yet.</p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {contacts.slice(0, 21).map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-3 rounded-xl border border-border bg-card p-3 transition-colors duration-200 hover:border-primary/25 hover:bg-muted/40"
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-xs font-semibold text-primary">
                  {(c.name || c.email || "?").charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {c.name || c.email || c.phone}
                  </p>
                  {c.email && <p className="truncate text-xs text-muted-foreground">{c.email}</p>}
                  {!c.email && c.phone && <p className="text-xs text-muted-foreground">{c.phone}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
