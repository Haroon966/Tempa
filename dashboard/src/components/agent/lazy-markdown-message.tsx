import { lazy, Suspense } from "react"

const MarkdownMessageLazy = lazy(() =>
  import("@/components/agent/markdown-message").then((m) => ({ default: m.MarkdownMessage })),
)

export function LazyMarkdownMessage(props: {
  content: string
  isStreaming?: boolean
  className?: string
}) {
  return (
    <Suspense
      fallback={
        <p className="whitespace-pre-wrap break-words text-sm text-foreground/90">{props.content}</p>
      }
    >
      <MarkdownMessageLazy {...props} />
    </Suspense>
  )
}
