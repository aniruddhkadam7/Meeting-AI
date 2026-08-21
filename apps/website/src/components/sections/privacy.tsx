"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "motion/react"
import { Video } from "lucide-react"
import { cn } from "@/lib/utils"
import { WaveformIllustration } from "@/components/blocks/waveform-illustration"
import { UploadControlIllustration } from "@/components/blocks/upload-control-illustration"
import { DocumentStackIllustration } from "@/components/blocks/document-stack-illustration"
import { SplitViewIllustration } from "@/components/blocks/split-view-illustration"

const points = [
  {
    number: "01",
    title: "A private panel, only you see",
    description: "Smallbird's assistance appears in its own window on your screen — separate from the call itself, and never part of what you share or present.",
    proof: <SplitViewIllustration />,
    proofLabel: "Your assistance stays in a separate window",
  },
  {
    number: "02",
    title: "Local speech processing",
    description: "Audio is transcribed locally on your device as part of the speech-to-text pipeline, rather than being streamed out for that step.",
    proof: <WaveformIllustration />,
    proofLabel: "Transcription runs on-device",
  },
  {
    number: "03",
    title: "You control what context you share",
    description: "CV, job description, and meeting documents are only used to help Smallbird understand your session — you choose what to upload.",
    proof: <UploadControlIllustration />,
    proofLabel: "Only what you add gets used",
  },
  {
    number: "04",
    title: "Privacy-conscious architecture",
    description: "Smallbird is designed to minimize what leaves your device wherever the product can support it, and we're upfront about the parts that involve a server.",
    proof: <DocumentStackIllustration />,
    proofLabel: "Context stays scoped to your session",
  },
]

export function Privacy() {
  const [active, setActive] = useState(0)

  return (
    <section id="privacy" className="scroll-mt-16 border-t border-border py-20 px-4 sm:py-28">
      <div id="security" className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Privacy by design
          </h2>
          <p className="mt-4 text-muted-foreground">
            Important conversations deserve a thoughtful approach to data.
            Here's how Smallbird is built — no unsupported claims, just what's
            actually true.
          </p>
        </div>

        <div className="mt-14 grid gap-10 lg:grid-cols-2 lg:items-center">
          <div className="space-y-1">
            {points.map((point, i) => (
              <button
                key={point.title}
                type="button"
                onClick={() => setActive(i)}
                className={cn(
                  "flex w-full items-center justify-between gap-4 border-b border-border py-4 text-left transition-colors",
                  active === i ? "text-foreground" : "text-muted-foreground hover:text-foreground/80",
                )}
              >
                <div>
                  <h3 className={cn("text-base font-medium", active === i && "text-foreground")}>
                    {point.title}
                  </h3>
                  {active === i ? (
                    <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
                      {point.description}
                    </p>
                  ) : null}
                </div>
                <span className="shrink-0 text-xs font-medium text-muted-foreground/60">
                  {point.number}
                </span>
              </button>
            ))}
          </div>

          <div className="glass relative flex h-72 items-center justify-center overflow-hidden rounded-2xl">
            <span className="absolute top-4 left-4 z-10 inline-flex items-center gap-1.5 rounded-full border border-border bg-background/80 px-3 py-1 text-xs font-medium text-foreground">
              <Video className="h-3 w-3" />
              {points[active].proofLabel}
            </span>
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3 }}
                className="flex w-full items-center justify-center px-8"
              >
                {points[active].proof}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  )
}
