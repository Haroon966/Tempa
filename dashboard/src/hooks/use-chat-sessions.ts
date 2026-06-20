import { useCallback, useEffect, useState } from "react"
import {
  createChatSession,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessions,
  type ChatSession,
  type ChatSessionSummary,
} from "@/lib/api"

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchChatSessions()
      setSessions(data.sessions)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const loadSession = useCallback(async (id: string) => {
    const session = await fetchChatSession(id)
    setActiveSession(session)
    return session
  }, [])

  const createSession = useCallback(async () => {
    const session = await createChatSession()
    await refresh()
    setActiveSession(session)
    return session
  }, [refresh])

  const removeSession = useCallback(
    async (id: string) => {
      await deleteChatSession(id)
      if (activeSession?.id === id) {
        setActiveSession(null)
      }
      await refresh()
    },
    [activeSession?.id, refresh],
  )

  return {
    sessions,
    activeSession,
    loading,
    refresh,
    loadSession,
    createSession,
    removeSession,
    setActiveSession,
  }
}
