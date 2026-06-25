import { CheckIcon, CopyIcon, TerminalIcon } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import type { QaAgentPlaybook } from "@/lib/api"

export function QaAgentPlaybookSheet({
  open,
  onOpenChange,
  playbook,
  title,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  playbook: QaAgentPlaybook | null
  title: string
}) {
  const [copied, setCopied] = useState<string | null>(null)

  async function copy(text: string, key: string) {
    await navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader className="text-left">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{playbook?.launch_hint}</SheetDescription>
        </SheetHeader>

        {playbook && (
          <div className="mt-6 flex flex-col gap-4 px-4 pb-8">
            {playbook.terminal_command && (
              <section>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Terminal
                </p>
                <div className="mt-2 flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3">
                  <TerminalIcon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <code className="flex-1 whitespace-pre-wrap break-all text-xs">{playbook.terminal_command}</code>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="shrink-0"
                    onClick={() => copy(playbook.terminal_command!, "term")}
                  >
                    {copied === "term" ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
                  </Button>
                </div>
              </section>
            )}

            <section>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Agent prompt
                </p>
                <Button size="sm" variant="outline" onClick={() => copy(playbook.prompt, "prompt")}>
                  {copied === "prompt" ? (
                    <>
                      <CheckIcon className="mr-1.5 size-3.5" /> Copied
                    </>
                  ) : (
                    <>
                      <CopyIcon className="mr-1.5 size-3.5" /> Copy prompt
                    </>
                  )}
                </Button>
              </div>
              <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-border bg-muted/30 p-3 text-xs leading-relaxed">
                {playbook.prompt}
              </pre>
            </section>

            <section>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Tempa curl commands
              </p>
              <ul className="mt-2 flex flex-col gap-2">
                {Object.entries(playbook.curl_commands).map(([key, cmd]) => (
                  <li key={key} className="rounded-lg border border-border/70 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium capitalize text-foreground">{key.replace(/_/g, " ")}</span>
                      <Button size="sm" variant="ghost" onClick={() => copy(cmd, key)}>
                        {copied === key ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
                      </Button>
                    </div>
                    <code className="mt-1 block whitespace-pre-wrap break-all text-[11px] text-muted-foreground">
                      {cmd}
                    </code>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
