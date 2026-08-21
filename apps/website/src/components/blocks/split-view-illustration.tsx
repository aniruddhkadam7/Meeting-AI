"use client"

import { Sparkles, Video } from "lucide-react"

export function SplitViewIllustration() {
  return (
    <div className="grid w-full max-w-md grid-cols-2 gap-3">
      <div className="flex flex-col gap-2">
        <span className="text-center text-[10px] font-medium text-muted-foreground">
          What they see
        </span>
        <div className="flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-lg border border-border bg-muted/40">
          <Video className="h-5 w-5 text-muted-foreground" />
          <div className="h-1.5 w-16 rounded-full bg-foreground/15" />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-center text-[10px] font-medium text-foreground">
          What you see
        </span>
        <div className="relative flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-lg border border-primary/30 bg-muted/40">
          <Video className="h-5 w-5 text-muted-foreground" />
          <div className="h-1.5 w-16 rounded-full bg-foreground/15" />
          <div className="glass absolute bottom-1.5 left-1.5 right-1.5 flex items-center gap-1.5 rounded-md px-2 py-1.5">
            <Sparkles className="h-3 w-3 shrink-0 text-primary" />
            <div className="h-1 w-full rounded-full bg-foreground/20" />
          </div>
        </div>
      </div>
    </div>
  )
}
