"use client"

import { motion } from "motion/react"
import { FolderOpen, Brain, Sparkles } from "lucide-react"
import { WaveformIllustration } from "@/components/blocks/waveform-illustration"

const steps = [
  {
    number: "01",
    title: "Context",
    description: "Your CV, job description, or meeting documents are loaded in.",
    preview: (
      <div className="glass-subtle flex w-full flex-col items-center justify-center gap-2 rounded-lg p-4">
        <FolderOpen className="h-6 w-6 text-primary" />
        <div className="w-full space-y-1">
          <div className="mx-auto h-1.5 w-3/4 rounded-full bg-foreground/15" />
          <div className="mx-auto h-1.5 w-1/2 rounded-full bg-foreground/10" />
        </div>
      </div>
    ),
  },
  {
    number: "02",
    title: "Listen",
    description: "Smallbird listens to the live conversation as it happens.",
    preview: (
      <div className="w-full">
        <WaveformIllustration />
      </div>
    ),
  },
  {
    number: "03",
    title: "Understand",
    description: "It connects what's being said to the context you've provided.",
    preview: (
      <div className="glass-subtle flex w-full flex-col items-center justify-center gap-2 rounded-lg p-4">
        <Brain className="h-6 w-6 text-primary" />
        <p className="text-[10px] text-muted-foreground">"debugging" → CV skills</p>
      </div>
    ),
  },
  {
    number: "04",
    title: "Assist",
    description: "You get relevant, real-time AI assistance right when you need it.",
    preview: (
      <div className="glass-subtle flex w-full flex-col items-center justify-center gap-2 rounded-lg p-4">
        <Sparkles className="h-6 w-6 text-primary" />
        <p className="text-[10px] text-muted-foreground">Suggested talking points</p>
      </div>
    ),
  },
]

export function HowItWorks() {
  return (
    <section className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Set up once. <span className="text-primary">Ready every session.</span>
          </h2>
          <p className="mt-4 text-muted-foreground">
            Smallbird runs in the background, knows your context, and assists
            from start to finish.
          </p>
        </div>

        <div className="mt-16 grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, i) => (
            <motion.div
              key={step.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.1, ease: "easeOut" }}
              className="flex flex-col gap-4"
            >
              <div className="glass flex h-28 items-center justify-center rounded-xl p-3">
                {step.preview}
              </div>
              <div>
                <span className="text-xs font-medium text-muted-foreground">{step.number}</span>
                <h3 className="mt-1 text-base font-medium text-foreground">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
