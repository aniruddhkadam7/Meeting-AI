import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { LiquidGlassContainer } from "@/components/ui/liquid-glass-container"
import { Mic, FileText, Sparkles } from "lucide-react"

export function AppMockupMeeting({ className }: { className?: string }) {
  return (
    <LiquidGlassContainer
      rounded="rounded-xl"
      className={cn("overflow-hidden", className)}
      style={{ backgroundColor: "rgba(255,255,255,0.35)" }}
    >
      <div className="flex items-center gap-2 border-b border-white/20 px-4 py-2.5 dark:border-white/10">
        <div className="flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-border" />
        </div>
        <span className="ml-2 text-xs font-medium text-muted-foreground">
          Smallbird — Meeting Mode
        </span>
        <Badge variant="secondary" className="ml-auto gap-1.5">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
          Listening
        </Badge>
      </div>

      <div className="grid gap-px bg-white/10 sm:grid-cols-[1.3fr_1fr]">
        <div className="flex flex-col gap-3 p-4 sm:p-5">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Mic className="h-3.5 w-3.5" />
            Live transcript
          </div>
          <div className="space-y-2.5 text-sm">
            <p className="text-muted-foreground">
              Client: "What's our timeline for the Q3 rollout given the
              staffing gap?"
            </p>
            <p className="glass-subtle rounded-md px-3 py-2 text-foreground">
              You: "Let me pull up what we scoped last quarter..."
            </p>
          </div>

          <div className="glass-subtle mt-2 flex items-start gap-2 rounded-lg p-3">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-foreground" />
            <div className="text-sm">
              <p className="mb-1 font-medium text-foreground">
                Relevant context surfaced
              </p>
              <p className="text-muted-foreground">
                Q3 rollout plan (uploaded doc) shows a 2-week buffer already
                built in for staffing — worth mentioning.
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3 p-4 sm:p-5">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <FileText className="h-3.5 w-3.5" />
            Meeting documents
          </div>
          <div className="space-y-2 text-xs">
            <div className="glass-subtle rounded-md p-2.5">
              <p className="font-medium text-foreground">Q3 Rollout Plan.pdf</p>
              <p className="mt-0.5 text-muted-foreground">Uploaded for this meeting</p>
            </div>
            <div className="glass-subtle rounded-md p-2.5">
              <p className="font-medium text-foreground">Client Notes</p>
              <p className="mt-0.5 text-muted-foreground">
                Prior engagement history &amp; context
              </p>
            </div>
          </div>
        </div>
      </div>
    </LiquidGlassContainer>
  )
}
