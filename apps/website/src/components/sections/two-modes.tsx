"use client"

import { motion } from "motion/react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Briefcase, Users } from "lucide-react"

const modes = [
  {
    icon: Briefcase,
    title: "Interview Mode",
    description:
      "Real-time AI assistance during interviews, grounded in your CV, the job description, and any extra context you provide.",
    useCase: "Use it when you're the one being interviewed and want relevant, well-informed responses on the spot.",
  },
  {
    icon: Users,
    title: "Meeting Mode",
    description:
      "Real-time AI assistance and context during meetings, drawing on the documents and background you bring in.",
    useCase: "Use it for client calls, standups, or any meeting where having the right context instantly matters.",
  },
]

export function TwoModes() {
  return (
    <section id="modes" className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Two modes, built for what matters
          </h2>
          <p className="mt-4 text-muted-foreground">
            Smallbird adapts to the conversation you're in.
          </p>
        </div>

        <div className="mt-14 grid gap-6 sm:grid-cols-2">
          {modes.map((mode, i) => (
            <motion.div
              key={mode.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.1, ease: "easeOut" }}
            >
              <Card className="h-full transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
                <CardHeader>
                  <div className="glass-subtle mb-2 flex h-10 w-10 items-center justify-center rounded-lg">
                    <mode.icon className="h-5 w-5 text-foreground" />
                  </div>
                  <CardTitle className="text-xl">{mode.title}</CardTitle>
                  <CardDescription className="text-base">{mode.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">{mode.useCase}</p>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
