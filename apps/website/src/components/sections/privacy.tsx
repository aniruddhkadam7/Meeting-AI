"use client"

import { motion } from "motion/react"
import { Lock, HardDrive, ShieldCheck } from "lucide-react"

const points = [
  {
    icon: HardDrive,
    title: "Speech processing stays on your machine",
    description: "Audio is transcribed locally on your device as part of the speech-to-text pipeline, rather than being streamed out for that step.",
  },
  {
    icon: Lock,
    title: "You control what context you share",
    description: "CV, job description, and meeting documents are only used to help Smallbird understand your session — you choose what to upload.",
  },
  {
    icon: ShieldCheck,
    title: "Built with a privacy-conscious architecture",
    description: "Smallbird is designed to minimize what leaves your device wherever the product can support it, and we're upfront about the parts that involve a server.",
  },
]

export function Privacy() {
  return (
    <section id="privacy" className="scroll-mt-16 border-t border-border py-20 px-4 sm:py-28">
      <div id="security" className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Privacy by design
          </h2>
          <p className="mt-4 text-muted-foreground">
            Important conversations deserve a thoughtful approach to data.
            Here's how Smallbird is built.
          </p>
        </div>

        <div className="mt-14 grid gap-8 sm:grid-cols-3">
          {points.map((point, i) => (
            <motion.div
              key={point.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.08, ease: "easeOut" }}
              className="text-center sm:text-left"
            >
              <div className="glass mx-auto flex h-10 w-10 items-center justify-center rounded-lg sm:mx-0">
                <point.icon className="h-5 w-5 text-foreground" />
              </div>
              <h3 className="mt-4 text-base font-medium text-foreground">{point.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{point.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
