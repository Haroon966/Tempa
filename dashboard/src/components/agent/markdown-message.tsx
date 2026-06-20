import { CheckIcon, CopyIcon } from "lucide-react"
import { useState } from "react"
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

export function MarkdownMessage({
  content,
  isStreaming = false,
  className,
}: {
  content: string
  isStreaming?: boolean
  className?: string
}) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none text-foreground prose-headings:text-foreground prose-p:text-foreground/90 prose-strong:text-foreground prose-a:text-primary prose-code:before:content-none prose-code:after:content-none prose-pre:bg-transparent prose-pre:p-0",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          code: ({ className: codeClass, children, ...props }) => {
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
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {content}
      </ReactMarkdown>
      {isStreaming && (
        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" />
      )}
    </div>
  )
}
