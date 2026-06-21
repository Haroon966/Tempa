import { useCallback, useEffect, useRef } from "react"

function findScrollViewport(node: HTMLElement | null): HTMLElement | null {
  let current: HTMLElement | null = node
  while (current) {
    if (current.dataset.slot === "scroll-area-viewport") {
      return current
    }
    current = current.parentElement
  }
  return null
}

export function useScrollToBottom<T extends HTMLElement>(deps: unknown[], enabled = true) {
  const anchorRef = useRef<T>(null)

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const anchor = anchorRef.current
    if (!anchor) return
    const viewport = findScrollViewport(anchor)
    if (viewport) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior })
      return
    }
    anchor.scrollIntoView({ behavior, block: "end" })
  }, [])

  useEffect(() => {
    if (!enabled) return
    scrollToBottom(deps.includes(true) ? "auto" : "smooth")
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps drive scroll timing
  }, deps)

  return { anchorRef, scrollToBottom }
}
