import { useEffect, useId, useRef, type RefObject } from "react"
import { Loader2Icon, SendIcon, SquareIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const MAX_INPUT_HEIGHT = 160

type ChatComposerProps = {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onStop?: () => void
  streaming?: boolean
  disabled?: boolean
  placeholder?: string
  className?: string
  inputRef?: RefObject<HTMLTextAreaElement | null>
  autoFocus?: boolean
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  streaming = false,
  disabled = false,
  placeholder = "Message Tempa…",
  className,
  inputRef,
  autoFocus = false,
}: ChatComposerProps) {
  const inputId = useId()
  const hintId = useId()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fieldRef = inputRef ?? textareaRef

  useEffect(() => {
    const el = fieldRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`
  }, [value, fieldRef])

  useEffect(() => {
    if (!autoFocus) return
    fieldRef.current?.focus()
  }, [autoFocus, fieldRef])

  const canSend = value.trim().length > 0 && !disabled && !streaming
  const inputDisabled = disabled

  return (
    <div
      className={cn(
        "shrink-0 border-t border-border bg-card/95 px-3 py-3 backdrop-blur-sm sm:px-4",
        "pb-[max(0.75rem,env(safe-area-inset-bottom))]",
        className,
      )}
    >
      {streaming && (
        <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2Icon className="size-3.5 shrink-0 motion-safe:animate-spin" aria-hidden />
          <span className="truncate">Tempa is working…</span>
        </p>
      )}

      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSend) onSubmit()
        }}
      >
        <div className="min-w-0 flex-1 rounded-xl border border-input bg-background shadow-sm transition-colors duration-200 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-ring/50">
          <label htmlFor={inputId} className="sr-only">
            Message Tempa
          </label>
          <textarea
            ref={fieldRef}
            id={inputId}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={1}
            disabled={inputDisabled}
            enterKeyHint="send"
            aria-describedby={hintId}
            className="block max-h-40 min-h-11 w-full resize-none bg-transparent px-3 py-2.5 text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-10 sm:px-4 sm:py-3 sm:text-sm"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                if (canSend) onSubmit()
              }
            }}
          />
        </div>

        {streaming ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-11 shrink-0 cursor-pointer transition-colors duration-200 sm:size-10"
            onClick={onStop}
            aria-label="Stop generating"
          >
            <SquareIcon className="size-4" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            className="size-11 shrink-0 cursor-pointer transition-colors duration-200 sm:size-10"
            disabled={!canSend}
            aria-label="Send message"
          >
            <SendIcon className="size-4" />
          </Button>
        )}
      </form>

      <p id={hintId} className="mt-2 hidden text-[11px] text-muted-foreground sm:block">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  )
}
