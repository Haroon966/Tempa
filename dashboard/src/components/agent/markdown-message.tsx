import { CheckIcon, CopyIcon } from "lucide-react"
import { useMemo, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { cn } from "@/lib/utils"
import { MermaidBlock } from "@/components/agent/mermaid-block"
import "highlight.js/styles/github.min.css"

function CodeBlock({
  className,
  children,
  isStreaming,
}: {
  className?: string
  children?: React.ReactNode
  isStreaming?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const match = /language-(\w+)/.exec(className ?? "")
  const lang = match?.[1] ?? ""
  const text = String(children ?? "").replace(/\n$/, "")

  if (lang === "mermaid") {
    return <MermaidBlock chart={text} isComplete={!isStreaming} />
  }

  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="group relative my-3">
      {lang && (
        <span className="absolute right-2 top-2 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
          {lang}
        </span>
      )}
      <button
        type="button"
        onClick={() => void copy()}
        className="absolute right-2 top-8 flex cursor-pointer items-center gap-1 rounded border border-border bg-background/90 px-2 py-1 text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
      >
        {copied ? <CheckIcon className="size-3" /> : <CopyIcon className="size-3" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed">
        <code className={className}>{children}</code>
      </pre>
    </div>
  )
}

function StreamingCursor() {
  return (
    <span
      className="ml-0.5 inline-block h-[1.1em] w-0.5 animate-pulse bg-primary align-text-bottom"
      aria-hidden
    />
  )
}

function splitStreamingBlocks(content: string): { complete: string; tail: string } {
  const parts = content.split(/\n\n/)
  if (parts.length <= 1) {
    return { complete: "", tail: content }
  }
  const tail = parts.pop() ?? ""
  return { complete: parts.join("\n\n"), tail }
}

export function MarkdownMessage({
  content,
  isStreaming = false,
  className,
}: {
  content: string
  isStreaming?: boolean
  className?: string
}) {
  const markdownComponents = useMemo(
    () => ({
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ),
      code: ({
        className: codeClass,
        children,
        ...props
      }: {
        className?: string
        children?: React.ReactNode
      }) => {
        const isBlock = String(children).includes("\n") || (codeClass ?? "").startsWith("language-")
        if (isBlock) {
          return (
            <CodeBlock className={codeClass} isStreaming={isStreaming}>
              {children}
            </CodeBlock>
          )
        }
        return (
          <code className={codeClass} {...props}>
            {children}
          </code>
        )
      },
      pre: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
      img: () => null,
    }),
    [isStreaming],
  )

  const proseClass = cn(
    "prose prose-sm max-w-none overflow-x-auto text-foreground prose-headings:text-foreground prose-p:text-foreground/90 prose-strong:text-foreground prose-a:text-primary prose-code:before:content-none prose-code:after:content-none prose-pre:bg-transparent prose-pre:p-0 prose-img:hidden",
    className,
  )

  if (isStreaming) {
    if (!content) {
      return (
        <div className={cn("text-sm leading-relaxed text-foreground/90", className)}>
          <p className="text-muted-foreground">Thinking…</p>
          <StreamingCursor />
        </div>
      )
    }

    const { complete, tail } = splitStreamingBlocks(content)
    return (
      <div className={cn("text-sm leading-relaxed text-foreground/90", className)}>
        {complete ? (
          <div className={proseClass}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {complete}
            </ReactMarkdown>
          </div>
        ) : null}
        {tail ? <p className="whitespace-pre-wrap break-words">{tail}</p> : null}
        <StreamingCursor />
      </div>
    )
  }

  if (!content.trim()) {
    return <p className="text-sm text-muted-foreground">No response.</p>
  }

  return (
    <div className={proseClass}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
