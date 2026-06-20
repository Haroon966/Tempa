import { useEffect, useRef, useState } from "react"
import {
  MessageSquareIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
  PlusIcon,
  SendIcon,
  ShieldCheckIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react"
import type { DashboardPayload } from "@/types/dashboard"
import type { NavSection } from "@/components/dashboard/nav"
import { useAgentChat } from "@/hooks/use-agent-chat"
import { useChatSessions } from "@/hooks/use-chat-sessions"
import { MarkdownMessage } from "@/components/agent/markdown-message"
import { PanelCard } from "@/components/dashboard/panel-card"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const EXAMPLE_PROMPTS = [
  "Search my Gmail for unread messages",
  "What's on my calendar this week?",
  "Search memory for recent meeting notes",
  "Summarize my latest WhatsApp conversations",
]

type AgentTabProps = {
  data: DashboardPayload
  onNavigate: (section: NavSection) => void
}

export function AgentTab({ data, onNavigate }: AgentTabProps) {
  const {
    sessions,
    loading: sessionsLoading,
    loadSession,
    createSession,
    removeSession,
    setActiveSession,
  } = useChatSessions()
  const {
    messages,
    streaming,
    activity,
    sendMessage,
    stop,
    setMessagesFromSession,
    clearActivity,
  } = useAgentChat()

  const [input, setInput] = useState("")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [showActivity, setShowActivity] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const groqConnected = data.connections.groq?.connected ?? false

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth" })
  }, [messages, streaming])

  const handleNewChat = async () => {
    const session = await createSession()
    setSessionId(session.id)
    setActiveSession(session)
    setMessagesFromSession([])
    clearActivity()
    setInput("")
  }

  const handleSelectSession = async (id: string) => {
    const session = await loadSession(id)
    setSessionId(session.id)
    setMessagesFromSession(session.messages)
    clearActivity()
  }

  const handleSend = async (text?: string) => {
    const message = (text ?? input).trim()
    if (!message) return
    setInput("")
    const { sessionId: resolvedId } = await sendMessage(message, sessionId)
    if (resolvedId && resolvedId !== sessionId) {
      setSessionId(resolvedId)
      const session = await loadSession(resolvedId)
      setActiveSession(session)
    }
  }

  const handleContinuePlan = async () => {
    await sendMessage("Continue with the approved plan.", sessionId, { plan_approved: true })
  }

  return (
    <div className="flex min-h-[calc(100vh-12rem)] flex-col gap-4 lg:flex-row">
      {/* Session sidebar */}
      <aside className="flex w-full shrink-0 flex-col gap-2 lg:w-56">
        <Button
          variant="outline"
          size="sm"
          className="cursor-pointer justify-start gap-2"
          onClick={() => void handleNewChat()}
        >
          <PlusIcon className="size-3.5" />
          New chat
        </Button>
        <ScrollArea className="h-48 rounded-xl border border-border bg-card lg:h-[calc(100vh-14rem)]">
          <div className="flex flex-col gap-0.5 p-2">
            {sessionsLoading && (
              <p className="px-2 py-3 text-xs text-muted-foreground">Loading sessions…</p>
            )}
            {!sessionsLoading && sessions.length === 0 && (
              <p className="px-2 py-3 text-xs text-muted-foreground">No sessions yet</p>
            )}
            {sessions.map((s) => (
              <div key={s.id} className="group flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => void handleSelectSession(s.id)}
                  className={cn(
                    "min-w-0 flex-1 cursor-pointer truncate rounded-lg px-2.5 py-2 text-left text-xs transition-colors",
                    sessionId === s.id
                      ? "bg-primary/10 text-primary"
                      : "text-foreground hover:bg-muted/60",
                  )}
                >
                  <span className="block truncate font-medium">{s.title}</span>
                  <span className="text-[10px] text-muted-foreground">{formatTime(s.updated_at)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => void removeSession(s.id)}
                  className="cursor-pointer rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                  aria-label="Delete session"
                >
                  <Trash2Icon className="size-3.5" />
                </button>
              </div>
            ))}
          </div>
        </ScrollArea>
      </aside>

      {/* Main chat */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {!groqConnected && (
          <Alert className="border-amber-200 bg-amber-50">
            <AlertTitle>Groq not connected</AlertTitle>
            <AlertDescription>
              Configure your API key in{" "}
              <button
                type="button"
                className="cursor-pointer font-medium text-primary underline"
                onClick={() => onNavigate("connections")}
              >
                Connections
              </button>{" "}
              to use the agent.
            </AlertDescription>
          </Alert>
        )}

        <PanelCard
          title="Agent"
          description="Chat with the Tempa coordinator — Gmail, calendar, memory, PC, and more"
          icon={MessageSquareIcon}
          action={
            <Button
              variant="ghost"
              size="sm"
              className="cursor-pointer gap-1.5 text-xs"
              onClick={() => setShowActivity((v) => !v)}
            >
              {showActivity ? (
                <PanelRightCloseIcon className="size-3.5" />
              ) : (
                <PanelRightOpenIcon className="size-3.5" />
              )}
              Activity
            </Button>
          }
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className={cn("grid min-h-0 flex-1 gap-4", showActivity && "lg:grid-cols-[1fr_240px]")}>
            <div className="flex min-h-0 flex-col">
              <ScrollArea className="min-h-[320px] flex-1 pr-2 lg:min-h-[420px]">
                {messages.length === 0 ? (
                  <div className="flex flex-col items-center gap-6 py-16 text-center">
                    <div className="flex size-14 items-center justify-center rounded-full border border-primary/25 bg-primary/8">
                      <MessageSquareIcon className="size-6 text-primary" />
                    </div>
                    <div>
                      <p className="font-medium text-foreground">Ask Tempa anything</p>
                      <p className="mt-1 max-w-md text-sm text-muted-foreground">
                        The coordinator routes your request to specialists — memory, Gmail, calendar,
                        Meet, WhatsApp, and PC tools.
                      </p>
                    </div>
                    <div className="flex flex-wrap justify-center gap-2">
                      {EXAMPLE_PROMPTS.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          onClick={() => void handleSend(prompt)}
                          disabled={streaming || !groqConnected}
                          className="cursor-pointer rounded-full border border-border bg-muted/40 px-3 py-1.5 text-xs text-foreground transition-colors hover:border-primary/30 hover:bg-muted/70 disabled:opacity-50"
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-4 pb-4">
                    {messages.map((msg) => (
                      <div
                        key={msg.id}
                        className={cn(
                          "rounded-xl border px-4 py-3",
                          msg.role === "user"
                            ? "ml-8 border-primary/20 bg-primary/5"
                            : "mr-4 border-border bg-muted/30",
                        )}
                      >
                        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                          {msg.role === "user" ? "You" : "Tempa"}
                        </p>
                        {msg.role === "user" ? (
                          <p className="whitespace-pre-wrap text-sm text-foreground">{msg.content}</p>
                        ) : (
                          <MarkdownMessage
                            content={msg.content || (msg.streaming ? "" : "…")}
                            isStreaming={msg.streaming}
                          />
                        )}
                        {msg.paused && (
                          <Alert className="mt-3 border-amber-200 bg-amber-50">
                            <ShieldCheckIcon className="size-4 text-amber-700" />
                            <AlertTitle className="text-amber-900">Approval required</AlertTitle>
                            <AlertDescription className="flex flex-wrap items-center gap-2 text-amber-800">
                              <span>Review the plan in Approvals before continuing.</span>
                              <Button
                                size="sm"
                                variant="outline"
                                className="cursor-pointer"
                                onClick={() => onNavigate("pending")}
                              >
                                Open Approvals
                              </Button>
                              <Button
                                size="sm"
                                className="cursor-pointer"
                                onClick={() => void handleContinuePlan()}
                                disabled={streaming}
                              >
                                Continue plan
                              </Button>
                            </AlertDescription>
                          </Alert>
                        )}
                        {msg.sources && msg.sources.length > 0 && !msg.streaming && (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {msg.sources.map((src, i) => (
                              <Badge
                                key={`${src.label ?? i}`}
                                variant="outline"
                                className="text-[10px] text-muted-foreground"
                              >
                                {src.label ?? src.tool ?? `Source ${i + 1}`}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={bottomRef} />
                  </div>
                )}
              </ScrollArea>

              <form
                className="mt-3 flex gap-2 border-t border-border pt-3"
                onSubmit={(e) => {
                  e.preventDefault()
                  void handleSend()
                }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Message Tempa…"
                  rows={2}
                  disabled={streaming || !groqConnected}
                  className="min-h-[4.5rem] flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none ring-ring/50 focus-visible:ring-2 disabled:opacity-50"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      void handleSend()
                    }
                  }}
                />
                {streaming ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="shrink-0 cursor-pointer"
                    onClick={stop}
                  >
                    <SquareIcon className="size-4" />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    size="icon"
                    className="shrink-0 cursor-pointer"
                    disabled={!input.trim() || !groqConnected}
                  >
                    <SendIcon className="size-4" />
                  </Button>
                )}
              </form>
            </div>

            {showActivity && (
              <ScrollArea className="hidden h-[420px] rounded-lg border border-border bg-muted/20 p-2 lg:block">
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Live activity
                </p>
                {activity.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {streaming ? "Waiting for agent events…" : "Activity appears during requests."}
                  </p>
                ) : (
                  <ol className="flex flex-col gap-2">
                    {activity.map((ev, i) => (
                      <li
                        key={`${ev.timestamp}-${i}`}
                        className="rounded-md border border-border bg-card p-2 text-xs"
                      >
                        <div className="flex items-center gap-1.5">
                          <Badge variant="outline" className="text-[10px]">
                            {ev.agent}
                          </Badge>
                          <span className="font-medium">{ev.action}</span>
                        </div>
                        {ev.detail && (
                          <p className="mt-1 text-muted-foreground">{ev.detail}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </ScrollArea>
            )}
          </div>
        </PanelCard>
      </div>
    </div>
  )
}
