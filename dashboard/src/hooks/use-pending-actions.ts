import { useCallback, useEffect, useState } from "react"
import {
  approvePendingAction,
  fetchPendingActions,
  rejectPendingAction,
  type PendingAction,
} from "@/lib/api"

export function usePendingActions(pollMs = 5000) {
  const [actions, setActions] = useState<PendingAction[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchPendingActions()
      setActions(data.actions)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), pollMs)
    return () => clearInterval(id)
  }, [refresh, pollMs])

  const approve = useCallback(
    async (id: string) => {
      await approvePendingAction(id)
      await refresh()
    },
    [refresh],
  )

  const reject = useCallback(
    async (id: string) => {
      await rejectPendingAction(id)
      await refresh()
    },
    [refresh],
  )

  return { actions, loading, refresh, approve, reject }
}
