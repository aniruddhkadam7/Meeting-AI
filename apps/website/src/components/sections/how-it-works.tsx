import { motion } from "motion/react"
import { FolderOpen, Ear, Brain, Sparkles } from "lucide-react"

const steps = [
  { icon: FolderOpen, title: "Context", description: "Your CV, job description, or meeting documents are loaded in." },
  { icon: Ear, title: "Listen", description: "Smallbird listens to the live conversation as it happens." },
  { icon: Brain, title: "Understand", description: "It connects what's being said to the context you've provided." },
  { icon: Sparkles, title: "Assist", description: "You get relevant, real-time AI assistance right when you need it." },
]

export function HowItWorks() {
  return (
    <section className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            How it works
          </h2>
        </div>

        <div className="relative mt-16 grid gap-10 sm:grid-cols-4 sm:gap-6">
          <div
            className="absolute top-6 left-0 right-0 hidden h-px bg-border sm:block"
            aria-hidden="true"
          />
          {steps.map((step, i) => (
            <motion.div
              key={step.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.1, ease: "easeOut" }}
              className="relative flex flex-col items-center text-center"
            >
              <div className="glass relative z-10 flex h-12 w-12 items-center justify-center rounded-full">
                <step.icon className="h-5 w-5 text-foreground" />
              </div>
              <h3 className="mt-4 text-base font-medium text-foreground">{step.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{step.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
