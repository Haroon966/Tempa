import { BrainIcon } from "lucide-react"
import type { ConnectionInfo } from "@/types/dashboard"
import { PanelCard } from "@/components/dashboard/panel-card"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"

type GroqSectionProps = {
  groq: ConnectionInfo | undefined
  groqKey: string
  setGroqKey: (v: string) => void
  groqBusy: boolean
  groqModels: string[]
  onSave: () => void
}

export function GroqSection({
  groq,
  groqKey,
  setGroqKey,
  groqBusy,
  groqModels,
  onSave,
}: GroqSectionProps) {
  return (
    <PanelCard
      title="Groq API"
      description="LLM, STT, and safety inference"
      icon={BrainIcon}
      action={<StatusBadge status={groq?.status ?? "disconnected"} />}
      contentClassName="flex flex-col gap-3"
    >
      {"detail" in (groq ?? {}) && typeof groq?.detail === "string" && groq.detail && (
        <p className="text-sm text-muted-foreground">{groq.detail}</p>
      )}
      {groqModels.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {groqModels.map((m) => (
            <Badge key={m} variant="outline" className="border-border bg-muted text-xs text-primary/70">
              {m}
            </Badge>
          ))}
        </div>
      )}
      <Input
        type="password"
        placeholder="GROQ_API_KEY"
        value={groqKey}
        onChange={(e) => setGroqKey(e.target.value)}
        autoComplete="off"
        aria-label="Groq API key"
        className="focus:border-primary/40"
      />
      <Button className="cursor-pointer" onClick={onSave} disabled={groqBusy}>
        {groqBusy ? "Testing…" : "Save & test"}
      </Button>
    </PanelCard>
  )
}
