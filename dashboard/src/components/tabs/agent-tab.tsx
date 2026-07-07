import { memo, useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import {
  HistoryIcon,
  Loader2Icon,
  MessageSquareIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { setAgentStreaming } from "@/lib/dashboard-streaming"
import { useDashboardData } from "@/contexts/dashboard-context"
import { useNavigateSection } from "@/hooks/use-navigate-section"
import { useScrollToBottom } from "@/hooks/use-scroll-to-bottom"
import { useAgentChat } from "@/hooks/use-agent-chat"
import { useChatSessions } from "@/hooks/use-chat-sessions"
import { ChatArtifactCards } from "@/components/agent/chat-artifact-cards"
import { ChatComposer } from "@/components/agent/chat-composer"
import {
  ConversationSidebarDesktop,
  ConversationSidebarSheet,
} from "@/components/agent/conversation-sidebar"
import { LazyMarkdownMessage } from "@/components/agent/lazy-markdown-message"
import { StreamingActivityFeed } from "@/components/agent/streaming-activity-feed"
import { MessageActions } from "@/components/agent/message-actions"
import { PendingActionCard } from "@/components/agent/pending-action-card"
import { SourceBadges } from "@/components/agent/source-badges"
import { PanelCard } from "@/components/dashboard/panel-card"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { formatTime } from "@/lib/format"
import type { ActivityEvent } from "@/types/dashboard"
import type { StepEvent } from "@/lib/api"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

const EXAMPLE_PROMPTS = [
  { text: "Search my Gmail for unread messages", requires: "gmail" as const },
  { text: "What's on my calendar this week?", requires: "google" as const },
  { text: "Search memory for recent meeting notes", requires: null },
  { text: "Summarize my latest WhatsApp conversations", requires: "whatsapp" as const },
]

type AgentTabProps = Record<string, never>

const ChatMessageBubble = memo(function ChatMessageBubble({
  msg,
  onContinuePlan,
  onOpenApprovals,
  onPendingResolved,
  onRetry,
  onNavigateData,
  streaming,
  liveSteps,
  liveActivity,
}: {
  msg: ReturnType<typeof useAgentChat>["messages"][number]
  onContinuePlan: () => void
  onOpenApprovals: () => void
  onPendingResolved: () => void
  onRetry?: () => void
  onNavigateData: () => void
  streaming: boolean
  liveSteps?: StepEvent[]
  liveActivity?: ActivityEvent[]
}) {
  const isUser = msg.role === "user"
  const displaySteps = liveSteps ?? msg.steps
  const displayActivity = liveActivity ?? msg.activity
  const hasActivity = Boolean(displaySteps?.length || displayActivity?.length)

  return (
    <div className={cn("group space-y-2", isUser && "text-right")}>
      <div className={cn("flex items-center gap-2", isUser && "justify-end")}>
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {isUser ? "You" : "Tempa"}
        </p>
        {msg.created_at && (
          <p className="text-[10px] text-muted-foreground/70 opacity-0 transition-opacity group-hover:opacity-100">
            {formatTime(msg.created_at)}
          </p>
        )}
        {!isUser && !msg.streaming && msg.content && (
          <MessageActions content={msg.content} onRetry={onRetry} disabled={streaming} />
        )}
      </div>
      <div
        className={cn(
          "max-w-full text-left",
          isUser &&
            "inline-block rounded-2xl border border-border bg-muted px-3 py-2.5 sm:px-4 sm:py-3",
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-sm text-foreground">{msg.content}</p>
        ) : (
          <div className="flex flex-col gap-3">
            {msg.content ? (
              <LazyMarkdownMessage content={msg.content} isStreaming={Boolean(msg.streaming)} />
            ) : msg.streaming && !hasActivity ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2Icon className="size-4 motion-safe:animate-spin text-primary" aria-hidden />
                Thinking…
              </p>
            ) : !msg.streaming && !hasActivity ? (
              <p className="text-sm text-muted-foreground">No response.</p>
            ) : msg.streaming && hasActivity ? null : null}
            {hasActivity ? (
              <StreamingActivityFeed
                steps={displaySteps ?? []}
                activity={displayActivity ?? []}
                live={Boolean(msg.streaming)}
              />
            ) : null}
          </div>
        )}
      </div>

      {msg.pending_actions?.map((action) => (
        <PendingActionCard
          key={action.id}
          preview={action}
          streaming={streaming}
          onContinuePlan={onContinuePlan}
          onResolved={onPendingResolved}
        />
      ))}

      {msg.paused && !msg.pending_actions?.length && (
        <Alert className="border-amber-200 bg-amber-50 text-left">
          <ShieldCheckIcon className="size-4 text-amber-700" />
          <AlertTitle className="text-amber-900">Approval required</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 text-amber-800 sm:flex-row sm:flex-wrap sm:items-center">
            <span className="break-words">Review the plan in Approvals before continuing.</span>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-9 cursor-pointer transition-colors duration-200"
                onClick={onOpenApprovals}
              >
                Open Approvals
              </Button>
              <Button
                size="sm"
                className="h-9 cursor-pointer transition-colors duration-200"
                onClick={onContinuePlan}
                disabled={streaming}
              >
                Continue plan
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {msg.artifacts && msg.artifacts.length > 0 && !msg.streaming && (
        <ChatArtifactCards artifacts={msg.artifacts} />
      )}

      {msg.sources && msg.sources.length > 0 && !msg.streaming && (
        <SourceBadges sources={msg.sources} alignRight={isUser} onNavigateData={onNavigateData} />
      )}
    </div>
  )
})

export function AgentTab(_props: AgentTabProps) {
  const { data } = useDashboardData()
  const navigate = useNavigate()
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>()
  const navigateSection = useNavigateSection()
  const {
    sessions,
    loading: sessionsLoading,
    loadSession,
    createSession,
    removeSession,
    setActiveSession,
    refresh: refreshSessions,
  } = useChatSessions()
  const {
    messages,
    streaming,
    activity,
    steps,
    sendMessage,
    stop,
    setMessagesFromSession,
    clearActivity,
    retryLastUserMessage,
  } = useAgentChat()

  const [input, setInput] = useState("")
  const [sessionId, setSessionId] = useState<string | null>(urlSessionId ?? null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [composerFocusKey, setComposerFocusKey] = useState(0)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const groqConnected = data?.connections.groq?.connected ?? false

  const { anchorRef: messagesEndRef } = useScrollToBottom<HTMLDivElement>(
    [messages.length, streaming, steps.length, activity.length, messages.at(-1)?.content?.length ?? 0],
    messages.length > 0,
  )

  useEffect(() => {
    setAgentStreaming(streaming)
    return () => setAgentStreaming(false)
  }, [streaming])

  const syncSessionUrl = (id: string | null) => {
    if (id) {
      navigate(`/agent/${id}`, { replace: true })
    } else {
      navigate("/agent", { replace: true })
    }
  }

  useEffect(() => {
    if (!urlSessionId || urlSessionId === sessionId) return
    void (async () => {
      try {
        const session = await loadSession(urlSessionId)
        setSessionId(session.id)
        setMessagesFromSession(session.messages)
        clearActivity()
      } catch {
        toast.error("Conversation not found")
        navigate("/agent", { replace: true })
      }
    })()
  }, [urlSessionId, sessionId, loadSession, setMessagesFromSession, clearActivity, navigate])

  const isPromptAvailable = (requires: "gmail" | "google" | "whatsapp" | null) => {
    if (!requires) return true
    if (requires === "gmail") return data?.connections.gmail?.connected ?? false
    if (requires === "google") return data?.connections.google?.connected ?? false
    if (requires === "whatsapp") return data?.connections.whatsapp?.connected ?? false
    return true
  }

  const handleNewChat = async () => {
    try {
      const session = await createSession()
      setSessionId(session.id)
      setActiveSession(session)
      setMessagesFromSession([])
      clearActivity()
      setInput("")
      setHistoryOpen(false)
      syncSessionUrl(session.id)
      setComposerFocusKey((k) => k + 1)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create chat")
    }
  }

  const handleSelectSession = async (id: string) => {
    try {
      const session = await loadSession(id)
      setSessionId(session.id)
      setMessagesFromSession(session.messages)
      clearActivity()
      setHistoryOpen(false)
      syncSessionUrl(session.id)
      setComposerFocusKey((k) => k + 1)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load chat")
    }
  }

  const handleDeleteSession = async (id: string) => {
    try {
      await removeSession(id)
      if (id === sessionId) {
        setSessionId(null)
        setActiveSession(null)
        setMessagesFromSession([])
        clearActivity()
        setInput("")
        syncSessionUrl(null)
        setComposerFocusKey((k) => k + 1)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete chat")
    }
  }

  const handleSend = async (text?: string) => {
    const message = (text ?? input).trim()
    if (!message) return
    setInput("")
    const { sessionId: resolvedId } = await sendMessage(message, sessionId)
    const activeId = resolvedId ?? sessionId
    if (activeId) {
      const isNewSession = resolvedId && resolvedId !== sessionId
      if (isNewSession) {
        setSessionId(resolvedId)
        syncSessionUrl(resolvedId)
      }
      void refreshSessions().then(async () => {
        try {
          const session = await loadSession(activeId)
          setActiveSession(session)
        } catch {
          /* keep streamed messages in UI */
        }
      })
    }
    setComposerFocusKey((k) => k + 1)
  }

  const reloadSession = async () => {
    if (!sessionId) return
    try {
      const session = await loadSession(sessionId)
      setMessagesFromSession(session.messages)
    } catch {
      /* ignore */
    }
  }

  const handleContinuePlan = async () => {
    await sendMessage("Continue with the approved plan.", sessionId, { plan_approved: true })
  }

  const activeSessionTitle =
    sessions.find((s) => s.id === sessionId)?.title ?? (sessionId ? "Current chat" : "New chat")

  const sidebarProps = {
    sessions,
    sessionsLoading,
    sessionId,
    onSelect: (id: string) => void handleSelectSession(id),
    onDelete: (id: string) => void handleDeleteSession(id),
    onNewChat: () => void handleNewChat(),
  }

  const availablePrompts = EXAMPLE_PROMPTS.filter((p) => isPromptAvailable(p.requires))

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3 overflow-hidden lg:h-full lg:flex-row lg:items-stretch lg:gap-4">
      <ConversationSidebarSheet
        {...sidebarProps}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
      />

      <ConversationSidebarDesktop {...sidebarProps} />

      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden">
        {!groqConnected && (
          <Alert className="shrink-0 border-amber-200 bg-amber-50">
            <AlertTitle>Groq not connected</AlertTitle>
            <AlertDescription className="break-words">
              Configure your API key in{" "}
              <button
                type="button"
                className="cursor-pointer font-medium text-primary underline transition-colors duration-200"
                onClick={() => navigateSection("settings")}
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
          titleClassName="hidden sm:block"
          descriptionClassName="hidden lg:block"
          headerClassName="hidden pb-0 sm:block sm:pb-3 lg:pb-4"
          action={
            <Button
              variant="outline"
              size="sm"
              className="h-9 cursor-pointer gap-1.5 transition-colors duration-200 lg:hidden"
              onClick={() => setHistoryOpen(true)}
            >
              <HistoryIcon className="size-3.5" />
              <span className="max-w-[7rem] truncate sm:max-w-[10rem]">{activeSessionTitle}</span>
            </Button>
          }
          className="flex min-h-0 flex-1 flex-col overflow-hidden py-0"
          contentClassName="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
        >
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <ScrollArea className="h-0 min-h-0 flex-1 basis-0">
                <div className="px-3 sm:px-4 lg:px-6">
                  {messages.length === 0 ? (
                    <div className="flex flex-col items-center gap-4 py-10 text-center sm:gap-6 sm:py-14">
                      <div className="flex size-12 items-center justify-center rounded-full border border-border bg-muted sm:size-14">
                        <MessageSquareIcon className="size-5 text-primary sm:size-6" />
                      </div>
                      <div className="max-w-md px-2">
                        <p className="font-medium text-foreground">Ask Tempa anything</p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          The coordinator routes your request to specialists — memory, Gmail, calendar,
                          Meet, WhatsApp, and PC tools.
                        </p>
                      </div>
                      <div className="grid w-full max-w-lg gap-2 px-2 sm:flex sm:flex-wrap sm:justify-center sm:px-0">
                        {availablePrompts.map((prompt) => (
                          <button
                            key={prompt.text}
                            type="button"
                            onClick={() => void handleSend(prompt.text)}
                            disabled={streaming || !groqConnected}
                            className="min-h-11 cursor-pointer rounded-xl border border-border bg-muted/40 px-3 py-2.5 text-left text-xs text-foreground transition-colors duration-200 hover:border-primary/30 hover:bg-muted/70 disabled:opacity-50 sm:min-h-0 sm:rounded-full sm:py-1.5 sm:text-center"
                          >
                            {prompt.text}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-4 py-3 sm:gap-6 sm:py-4">
                      {messages.map((msg, index) => (
                        <ChatMessageBubble
                          key={msg.id}
                          msg={msg}
                          streaming={streaming}
                          liveSteps={msg.streaming && msg.role === "assistant" ? steps : undefined}
                          liveActivity={msg.streaming && msg.role === "assistant" ? activity : undefined}
                          onContinuePlan={() => void handleContinuePlan()}
                          onOpenApprovals={() => navigateSection("inbox")}
                          onPendingResolved={() => void reloadSession()}
                          onNavigateData={() => navigateSection("meetings")}
                          onRetry={
                            msg.role === "assistant" && index === messages.length - 1
                              ? () => void retryLastUserMessage(sessionId)
                              : undefined
                          }
                        />
                      ))}
                      <div ref={messagesEndRef} className="h-px shrink-0" aria-hidden />
                    </div>
                  )}
                </div>
              </ScrollArea>

            <ChatComposer
                key={composerFocusKey}
                value={input}
                onChange={setInput}
                onSubmit={() => void handleSend()}
                onStop={stop}
                streaming={streaming}
                disabled={!groqConnected}
                inputRef={composerRef}
                autoFocus
            />
          </div>
        </PanelCard>
      </div>
    </div>
  )
}
