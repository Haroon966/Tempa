import { CheckIcon, CopyIcon, RotateCcwIcon } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type MessageActionsProps = {
  content: string
  onRetry?: () => void
  disabled?: boolean
  className?: string
}

export function MessageActions({ content, onRetry, disabled, className }: MessageActionsProps) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div
      className={cn(
        "flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100",
        className,
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-8 cursor-pointer"
        onClick={() => void copy()}
        aria-label="Copy message"
      >
        {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
      </Button>
      {onRetry && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 cursor-pointer"
          onClick={onRetry}
          disabled={disabled}
          aria-label="Retry message"
        >
          <RotateCcwIcon className="size-3.5" />
        </Button>
      )}
    </div>
  )
}
