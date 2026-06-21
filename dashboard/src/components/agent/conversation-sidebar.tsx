import { useState } from "react"
import {
  MessageSquareIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"
import type { ChatSessionSummary } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

type ConversationSidebarProps = {
  sessions: ChatSessionSummary[]
  sessionsLoading: boolean
  sessionId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onNewChat: () => void
  /** Mobile sheet */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
}

function SessionRow({
  session,
  active,
  onSelect,
  onDelete,
  showDeleteAlways,
  confirmDeleteId,
  onConfirmDelete,
  onCancelDelete,
}: {
  session: ChatSessionSummary
  active: boolean
  onSelect: () => void
  onDelete: () => void
  showDeleteAlways?: boolean
  confirmDeleteId: string | null
  onConfirmDelete: () => void
  onCancelDelete: () => void
}) {
  const confirming = confirmDeleteId === session.id

  return (
    <div className="group flex items-stretch gap-0.5">
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "flex min-h-11 min-w-0 flex-1 cursor-pointer flex-col justify-center rounded-lg border border-transparent px-3 py-2 text-left transition-colors duration-200",
          active
            ? "border-primary/20 bg-primary/10 text-primary"
            : "text-foreground hover:border-border hover:bg-muted/60",
        )}
      >
        <span className="flex items-center gap-2">
          <MessageSquareIcon
            className={cn(
              "size-3.5 shrink-0",
              active ? "text-primary" : "text-muted-foreground",
            )}
            aria-hidden
          />
          <span className="truncate text-sm font-medium">{session.title}</span>
        </span>
        <span className="mt-0.5 pl-5 text-[11px] text-muted-foreground">
          {formatTime(session.updated_at)}
        </span>
      </button>
      {confirming ? (
        <div className="flex shrink-0 items-center gap-1 px-1">
          <Button
            size="sm"
            variant="destructive"
            className="h-9 cursor-pointer px-2 text-xs"
            onClick={onConfirmDelete}
          >
            Delete
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-9 cursor-pointer px-2 text-xs"
            onClick={onCancelDelete}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          className={cn(
            "flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors duration-200 hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            showDeleteAlways
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
          )}
          aria-label={`Delete ${session.title}`}
        >
          <Trash2Icon className="size-4" />
        </button>
      )}
    </div>
  )
}

export function ConversationList({
  sessions,
  sessionsLoading,
  sessionId,
  onSelect,
  onDelete,
  showDeleteAlways = false,
}: {
  sessions: ChatSessionSummary[]
  sessionsLoading: boolean
  sessionId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  showDeleteAlways?: boolean
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  if (sessionsLoading) {
    return (
      <div className="flex flex-col gap-2 px-2 py-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-11 animate-pulse rounded-lg bg-muted/60 motion-reduce:animate-none" />
        ))}
      </div>
    )
  }

  if (sessions.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
        <div className="flex size-10 items-center justify-center rounded-full border border-border bg-muted/40">
          <MessageSquareIcon className="size-4 text-muted-foreground" aria-hidden />
        </div>
        <p className="text-sm font-medium text-foreground">No conversations yet</p>
        <p className="text-xs text-muted-foreground">Start a new chat to talk with Tempa.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 p-2">
      {sessions.map((session) => (
        <SessionRow
          key={session.id}
          session={session}
          active={sessionId === session.id}
          onSelect={() => onSelect(session.id)}
          onDelete={() => setConfirmDeleteId(session.id)}
          showDeleteAlways={showDeleteAlways}
          confirmDeleteId={confirmDeleteId}
          onConfirmDelete={() => {
            onDelete(session.id)
            setConfirmDeleteId(null)
            toast.success("Conversation deleted")
          }}
          onCancelDelete={() => setConfirmDeleteId(null)}
        />
      ))}
    </div>
  )
}

export function ConversationSidebarPanel({
  sessions,
  sessionsLoading,
  sessionId,
  onSelect,
  onDelete,
  onNewChat,
  showDeleteAlways = false,
  className,
}: Omit<ConversationSidebarProps, "open" | "onOpenChange"> & {
  showDeleteAlways?: boolean
}) {
  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card",
        className,
      )}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">Conversations</p>
          <p className="text-[11px] text-muted-foreground">
            {sessionsLoading ? "Loading…" : `${sessions.length} saved`}
          </p>
        </div>
        <Button
          size="sm"
          className="h-9 shrink-0 cursor-pointer gap-1.5 px-3 transition-colors duration-200"
          onClick={onNewChat}
        >
          <PlusIcon className="size-3.5" />
          <span className="hidden sm:inline">New chat</span>
          <span className="sm:hidden">New</span>
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1 basis-0">
        <ConversationList
          sessions={sessions}
          sessionsLoading={sessionsLoading}
          sessionId={sessionId}
          onSelect={onSelect}
          onDelete={onDelete}
          showDeleteAlways={showDeleteAlways}
        />
      </ScrollArea>
    </div>
  )
}

/** Desktop sidebar — visible lg+ */
export function ConversationSidebarDesktop(props: ConversationSidebarProps) {
  return (
    <aside
      className={cn(
        "hidden min-h-0 shrink-0 self-stretch lg:flex lg:w-60 xl:w-64",
        props.className,
      )}
    >
      <ConversationSidebarPanel {...props} className="h-full w-full" />
    </aside>
  )
}

/** Mobile sheet drawer */
export function ConversationSidebarSheet({
  open,
  onOpenChange,
  ...props
}: ConversationSidebarProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="left"
        className="flex h-full max-h-[100dvh] w-[min(100vw-1rem,22rem)] flex-col gap-0 p-0 sm:max-w-sm"
      >
        <SheetHeader className="shrink-0 border-b border-border px-4 py-4 text-left">
          <SheetTitle>Conversations</SheetTitle>
          <SheetDescription>Switch between chats or start a new one.</SheetDescription>
        </SheetHeader>
        <ScrollArea className="min-h-0 flex-1 basis-0">
          <ConversationList
            sessions={props.sessions}
            sessionsLoading={props.sessionsLoading}
            sessionId={props.sessionId}
            onSelect={props.onSelect}
            onDelete={props.onDelete}
            showDeleteAlways
          />
        </ScrollArea>
        <div className="shrink-0 border-t border-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button
            className="h-11 w-full cursor-pointer gap-2 transition-colors duration-200"
            onClick={props.onNewChat}
          >
            <PlusIcon className="size-4" />
            New chat
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
