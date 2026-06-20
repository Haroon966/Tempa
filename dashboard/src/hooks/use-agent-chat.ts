import { useCallback, useRef, useState } from "react"
import { streamChat, type ChatSource } from "@/lib/api"
import type { ActivityEvent } from "@/types/dashboard"

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: ChatSource[]
  paused?: boolean
  streaming?: boolean
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export function useAgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const abortRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(
    async (
      text: string,
      sessionId: string | null,
      context: Record<string, unknown> = {},
    ): Promise<{ sessionId: string | null; paused: boolean }> => {
      const trimmed = text.trim()
      if (!trimmed || streaming) {
        return { sessionId, paused: false }
      }

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const userMsg: ChatMessage = { id: newId(), role: "user", content: trimmed }
      const assistantId = newId()
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: "assistant", content: "", streaming: true },
      ])
      setStreaming(true)
      setActivity([])

      let resolvedSessionId = sessionId
      let paused = false

      try {
        for await (const event of streamChat(
          { message: trimmed, session_id: sessionId, context },
          controller.signal,
        )) {
          if (event.type === "token") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + event.delta }
                  : m,
              ),
            )
          } else if (event.type === "activity") {
            setActivity((prev) => [...prev.slice(-49), event.event])
          } else if (event.type === "message") {
            resolvedSessionId = event.session_id ?? resolvedSessionId
            paused = event.paused
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: event.content || m.content,
                      sources: event.sources,
                      paused: event.paused,
                      streaming: false,
                    }
                  : m,
              ),
            )
          } else if (event.type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: `Error: ${event.error}`,
                      streaming: false,
                    }
                  : m,
              ),
            )
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: `Error: ${(err as Error).message}`,
                    streaming: false,
                  }
                : m,
            ),
          )
        } else {
          setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
      }

      return { sessionId: resolvedSessionId, paused }
    },
    [streaming],
  )

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setStreaming(false)
  }, [])

  const setMessagesFromSession = useCallback(
    (sessionMessages: Array<{ id: string; role: string; content: string; sources?: ChatSource[] }>) => {
      setMessages(
        sessionMessages.map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          sources: m.sources,
        })),
      )
    },
    [],
  )

  const clearActivity = useCallback(() => setActivity([]), [])

  return {
    messages,
    streaming,
    activity,
    sendMessage,
    stop,
    setMessagesFromSession,
    clearActivity,
  }
}
