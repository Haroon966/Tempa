import { useCallback, useRef, useState } from "react"
import {
  cancelChatRun,
  streamChat,
  type ChatArtifact,
  type ChatSource,
  type PendingActionPreview,
  type StepEvent,
} from "@/lib/api"
import type { ActivityEvent } from "@/types/dashboard"

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: ChatSource[]
  paused?: boolean
  pending_actions?: PendingActionPreview[]
  artifacts?: ChatArtifact[]
  created_at?: string
  streaming?: boolean
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export function useAgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [steps, setSteps] = useState<StepEvent[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const streamingRef = useRef(false)
  const runIdRef = useRef<string | null>(null)

  const sendMessage = useCallback(
    async (
      text: string,
      sessionId: string | null,
      context: Record<string, unknown> = {},
    ): Promise<{ sessionId: string | null; paused: boolean }> => {
      const trimmed = text.trim()
      if (!trimmed || streamingRef.current) {
        return { sessionId, paused: false }
      }

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      runIdRef.current = null

      const userMsg: ChatMessage = { id: newId(), role: "user", content: trimmed }
      const assistantId = newId()
      const contentRef = { current: "" }
      let finalized = false

      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: "assistant", content: "", streaming: true },
      ])
      streamingRef.current = true
      setStreaming(true)
      setActivity([])
      setSteps([])

      let resolvedSessionId = sessionId
      let paused = false

      const updateAssistant = (patch: Partial<ChatMessage>) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)),
        )
      }

      const applyToken = (delta: string) => {
        if (!delta || finalized) return
        contentRef.current += delta
        updateAssistant({ content: contentRef.current, streaming: true })
      }

      const finalizeAssistant = (patch: Partial<ChatMessage> = {}) => {
        if (finalized) return
        finalized = true

        const patchContent = patch.content?.trim() ?? ""
        const content = patchContent || contentRef.current
        contentRef.current = content

        updateAssistant({
          ...patch,
          content,
          streaming: false,
        })
      }

      try {
        for await (const event of streamChat(
          { message: trimmed, session_id: sessionId, context, run_id: runIdRef.current },
          controller.signal,
        )) {
          if (event.type === "run_started") {
            runIdRef.current = event.run_id
          } else if (event.type === "token") {
            applyToken(event.delta)
          } else if (event.type === "activity") {
            setActivity((prev) => [...prev.slice(-49), event.event])
          } else if (event.type === "step") {
            setSteps((prev) => {
              const existing = prev.findIndex(
                (s) => s.subtask_id === event.step.subtask_id && s.status === "start",
              )
              if (event.step.status === "start") {
                return [...prev.slice(-49), event.step]
              }
              if (existing >= 0) {
                const next = [...prev]
                next[existing] = { ...next[existing], ...event.step }
                return next
              }
              return [...prev.slice(-49), event.step]
            })
          } else if (event.type === "message") {
            resolvedSessionId = event.session_id ?? resolvedSessionId
            paused = event.paused
            runIdRef.current = event.run_id ?? runIdRef.current
            finalizeAssistant({
              content: event.content,
              sources: event.sources,
              paused: event.paused,
              pending_actions: event.pending_actions,
              artifacts: event.artifacts,
            })
          } else if (event.type === "error") {
            finalizeAssistant({ content: `Error: ${event.error}` })
          } else if (event.type === "done") {
            finalizeAssistant()
          }
        }

        if (!finalized) {
          finalizeAssistant()
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          finalizeAssistant({ content: `Error: ${(err as Error).message}` })
        } else if (!finalized) {
          updateAssistant({
            content: contentRef.current,
            streaming: false,
          })
          finalized = true
        }
      } finally {
        streamingRef.current = false
        setStreaming(false)
        abortRef.current = null
        runIdRef.current = null
      }

      return { sessionId: resolvedSessionId, paused }
    },
    [],
  )

  const stop = useCallback(() => {
    const runId = runIdRef.current
    if (runId) {
      void cancelChatRun(runId).catch(() => undefined)
    }
    abortRef.current?.abort()
    streamingRef.current = false
    setStreaming(false)
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    )
  }, [])

  const setMessagesFromSession = useCallback(
    (
      sessionMessages: Array<{
        id: string
        role: string
        content: string
        sources?: ChatSource[]
        paused?: boolean
        created_at?: string
      }>,
    ) => {
      setMessages(
        sessionMessages.map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          sources: m.sources,
          paused: m.paused,
          created_at: m.created_at,
          streaming: false,
        })),
      )
    },
    [],
  )

  const clearActivity = useCallback(() => {
    setActivity([])
    setSteps([])
  }, [])

  const retryLastUserMessage = useCallback(
    async (sessionId: string | null) => {
      const lastUser = [...messages].reverse().find((m) => m.role === "user")
      if (!lastUser) return { sessionId, paused: false }
      setMessages((prev) => prev.filter((m) => m.id !== lastUser.id))
      return sendMessage(lastUser.content, sessionId)
    },
    [messages, sendMessage],
  )

  return {
    messages,
    streaming,
    activity,
    steps,
    sendMessage,
    stop,
    setMessagesFromSession,
    clearActivity,
    retryLastUserMessage,
  }
}
