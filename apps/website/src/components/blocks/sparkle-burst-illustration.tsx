"use client"

import { motion } from "motion/react"
import { Sparkles } from "lucide-react"

const particles = [
  { x: -36, y: -22, delay: 0 },
  { x: 34, y: -28, delay: 0.3 },
  { x: -30, y: 24, delay: 0.6 },
  { x: 38, y: 20, delay: 0.9 },
  { x: 0, y: -34, delay: 1.2 },
]

export function SparkleBurstIllustration() {
  return (
    <div className="relative flex h-32 w-full items-center justify-center">
      {particles.map((p, i) => (
        <motion.span
          key={i}
          className="absolute h-1.5 w-1.5 rounded-full bg-primary/70"
          style={{ left: "50%", top: "50%" }}
          animate={{
            x: [0, p.x],
            y: [0, p.y],
            opacity: [0, 1, 0],
            scale: [0.4, 1, 0.4],
          }}
          transition={{
            duration: 2.4,
            repeat: Infinity,
            delay: p.delay,
            ease: "easeInOut",
          }}
        />
      ))}
      <motion.div
        className="glass flex h-14 w-14 items-center justify-center rounded-full"
        animate={{ scale: [1, 1.08, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      >
        <Sparkles className="h-6 w-6 text-primary" />
      </motion.div>
    </div>
  )
}
