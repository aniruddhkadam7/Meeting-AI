import { useEffect, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { Mic, FileSearch, Sparkles, AudioLines } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const stages = [
  {
    key: "listen",
    icon: Mic,
    label: "Listening",
    title: "Interviewer",
    body: "“Can you walk me through a time you had to debug a tricky production issue?”",
  },
  {
    key: "transcribe",
    icon: AudioLines,
    label: "Transcribing",
    title: "Live transcript",
    body: "“Sure — we had a memory leak that only showed up under load...”",
  },
  {
    key: "context",
    icon: FileSearch,
    label: "Matching context",
    title: "CV + Job Description",
    body: "4 yrs backend, distributed systems — matches “debugging” in the role.",
  },
  {
    key: "assist",
    icon: Sparkles,
    label: "Assisting",
    title: "Suggested talking points",
    body: "Mention the profiling tool, the root cause, and the monitoring you added after.",
  },
] as const

export function HeroGlassOverlay({ className }: { className?: string }) {
  const [index, setIndex] = useState(0)
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    setReducedMotion(mq.matches)
    const onChange = () => setReducedMotion(mq.matches)
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  useEffect(() => {
    if (reducedMotion) return
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % stages.length)
    }, 3200)
    return () => clearInterval(id)
  }, [reducedMotion])

  const stage = stages[index]

  return (
    <div
      className={cn(
        "relative isolate flex min-h-[420px] w-full items-center justify-center overflow-hidden rounded-2xl",
        className,
      )}
    >
      {/* Ambient backdrop — soft color blobs give the glass blur something to bend */}
      <div className="absolute inset-0 bg-[linear-gradient(135deg,oklch(0.97_0_0)_0%,oklch(0.99_0_0)_50%,oklch(0.95_0_0)_100%)] dark:bg-[linear-gradient(135deg,oklch(0.18_0_0)_0%,oklch(0.14_0_0)_50%,oklch(0.2_0_0)_100%)]" />

      <motion.div
        aria-hidden="true"
        className="absolute -left-16 top-8 h-64 w-64 rounded-full bg-violet-400/40 blur-3xl dark:bg-violet-500/25"
        animate={reducedMotion ? undefined : { x: [0, 30, 0], y: [0, 20, 0] }}
        transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        aria-hidden="true"
        className="absolute -right-10 bottom-4 h-72 w-72 rounded-full bg-sky-400/40 blur-3xl dark:bg-sky-500/20"
        animate={reducedMotion ? undefined : { x: [0, -25, 0], y: [0, -15, 0] }}
        transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        aria-hidden="true"
        className="absolute left-1/3 bottom-0 h-56 w-56 rounded-full bg-amber-300/30 blur-3xl dark:bg-amber-500/10"
        animate={reducedMotion ? undefined : { x: [0, 15, 0], y: [0, -10, 0] }}
        transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
      />

      <div className="absolute inset-0 opacity-[0.05] [background-image:radial-gradient(circle_at_1px_1px,currentColor_1px,transparent_0)] [background-size:22px_22px]" />

      {/* Floating glass panel */}
      <div className="relative z-10 w-full max-w-md overflow-hidden rounded-2xl border border-white/40 bg-white/25 p-5 shadow-[0_8px_40px_-8px_rgba(0,0,0,0.3),inset_0_1px_0_0_rgba(255,255,255,0.5)] backdrop-blur-2xl backdrop-saturate-150 dark:border-white/15 dark:bg-white/[0.07] dark:shadow-[0_8px_40px_-8px_rgba(0,0,0,0.6),inset_0_1px_0_0_rgba(255,255,255,0.08)]">
        {/* subtle top sheen */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/70 to-transparent" />

        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-foreground/70">
            Smallbird
          </span>
          <Badge
            variant="secondary"
            className="gap-1.5 border border-white/30 bg-white/40 backdrop-blur-sm dark:border-white/10 dark:bg-white/10"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
            Live
          </Badge>
        </div>

        <div className="mt-5 h-[168px]">
          <AnimatePresence mode="wait">
            <motion.div
              key={stage.key}
              initial={reducedMotion ? false : { opacity: 0, y: 10, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={reducedMotion ? undefined : { opacity: 0, y: -10, filter: "blur(4px)" }}
              transition={{ duration: 0.45, ease: "easeOut" }}
              className="flex h-full flex-col"
            >
              <div className="flex items-center gap-2 text-xs font-medium text-foreground/60">
                <stage.icon className="h-3.5 w-3.5" />
                {stage.label}
              </div>
              <div className="mt-3 flex-1 rounded-xl border border-white/30 bg-white/30 p-4 backdrop-blur-md dark:border-white/10 dark:bg-white/[0.05]">
                <p className="text-xs font-medium text-foreground/70">
                  {stage.title}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-foreground">
                  {stage.body}
                </p>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="mt-5 flex justify-center gap-1.5">
          {stages.map((s, i) => (
            <span
              key={s.key}
              className={cn(
                "h-1 rounded-full transition-all duration-300",
                i === index ? "w-6 bg-foreground/70" : "w-1.5 bg-foreground/25",
              )}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
