"use client"

import { motion } from "motion/react"
import { useRouter } from "next/navigation"
import { AudioLines, Sparkles, ArrowRight, FileText } from "lucide-react"
import { LiquidButton } from "@/components/ui/liquid-glass-button"
import { DocumentStackIllustration } from "@/components/blocks/document-stack-illustration"
import { WaveformIllustration } from "@/components/blocks/waveform-illustration"
import { SparkleBurstIllustration } from "@/components/blocks/sparkle-burst-illustration"

export function Advantages() {
  const router = useRouter()

  return (
    <section className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            <span className="text-primary">Everything you need</span>, mid-conversation
          </h2>
          <p className="mt-4 text-muted-foreground">
            Context, transcription, and assistance — handled live while the
            conversation is still happening.
          </p>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="glass mt-14 overflow-hidden rounded-2xl"
        >
          <div className="grid gap-px bg-border/60 sm:grid-cols-[1fr_1.2fr]">
            <div className="flex flex-col justify-center gap-3 p-8">
              <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
                <FileText className="h-3 w-3" />
                Context
              </span>
              <h3 className="text-xl font-semibold text-foreground">
                CV, job description, and document context
              </h3>
              <p className="text-sm text-muted-foreground">
                Load your resume and the job description before an interview,
                or bring in meeting documents beforehand — Smallbird grounds
                its assistance in what you actually gave it.
              </p>
            </div>
            <div className="flex items-center justify-center bg-foreground/[0.02] p-6">
              <DocumentStackIllustration />
            </div>
          </div>
        </motion.div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5, delay: 0.1, ease: "easeOut" }}
            className="glass overflow-hidden rounded-2xl"
          >
            <div className="flex items-center justify-center bg-foreground/[0.02] pt-6">
              <WaveformIllustration />
            </div>
            <div className="p-6 pt-4">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
                <AudioLines className="h-3 w-3" />
                Speech Recognition
              </span>
              <h3 className="mt-4 text-lg font-semibold text-foreground">
                Local, real-time transcription
              </h3>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Speech-to-text runs on your machine, keeping the audio pipeline
                close to home as the conversation happens.
              </p>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5, delay: 0.18, ease: "easeOut" }}
            className="glass overflow-hidden rounded-2xl"
          >
            <div className="flex items-center justify-center bg-foreground/[0.02] pt-6">
              <SparkleBurstIllustration />
            </div>
            <div className="p-6 pt-4">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
                <Sparkles className="h-3 w-3" />
                AI Assistance
              </span>
              <h3 className="mt-4 text-lg font-semibold text-foreground">
                Context-aware, relevant responses
              </h3>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Suggestions are generated as the conversation unfolds, grounded
                in the context you've loaded in.
              </p>
            </div>
          </motion.div>
        </div>

        <div className="mt-10 flex flex-col items-center gap-2">
          <LiquidButton size="lg" onClick={() => router.push("/download")}>
            Get Started
            <ArrowRight className="h-4 w-4" />
          </LiquidButton>
          <p className="text-xs text-muted-foreground">No card required</p>
        </div>
      </div>
    </section>
  )
}
