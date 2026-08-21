"use client"

import { motion } from "motion/react"

const bars = [6, 12, 20, 14, 28, 18, 34, 22, 30, 16, 24, 12, 20, 8, 14]

export function WaveformIllustration() {
  return (
    <div className="flex h-20 w-full items-center justify-center gap-[3px]">
      {bars.map((height, i) => (
        <motion.span
          key={i}
          className="w-1.5 rounded-full bg-gradient-to-t from-primary/40 to-primary"
          style={{ height }}
          animate={{ scaleY: [1, 1.6, 0.7, 1.3, 1] }}
          transition={{
            duration: 1.6,
            repeat: Infinity,
            repeatType: "mirror",
            delay: i * 0.06,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  )
}
