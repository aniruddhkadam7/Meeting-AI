import { motion } from "motion/react"
import { Zap, FileStack, Cpu, Sparkles, Monitor, Gauge } from "lucide-react"

const advantages = [
  { icon: Zap, title: "Real-time assistance", description: "Get relevant help while the conversation is still happening — not after." },
  { icon: FileStack, title: "CV/JD and document context", description: "Load your resume, job description, or meeting documents so responses are grounded in your actual situation." },
  { icon: Cpu, title: "Local speech processing", description: "Speech-to-text runs on your machine, keeping the audio pipeline close to home." },
  { icon: Sparkles, title: "AI-powered responses", description: "Get relevant, context-aware suggestions generated as the conversation unfolds." },
  { icon: Monitor, title: "Windows desktop experience", description: "A native desktop app built for focus during high-stakes conversations." },
  { icon: Gauge, title: "Adaptive performance", description: "Smallbird adjusts to your hardware so it runs smoothly across different machines." },
]

export function Advantages() {
  return (
    <section className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Built for the moment it matters
          </h2>
        </div>

        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {advantages.map((item, i) => (
            <motion.div
              key={item.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.06, ease: "easeOut" }}
              className="glass rounded-xl p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg"
            >
              <item.icon className="h-5 w-5 text-foreground" />
              <h3 className="mt-4 text-base font-medium text-foreground">{item.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{item.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
