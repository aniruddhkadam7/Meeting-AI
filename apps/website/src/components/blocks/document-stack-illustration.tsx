"use client"

import { motion } from "motion/react"
import { FileText } from "lucide-react"

export function DocumentStackIllustration() {
  return (
    <div className="relative flex h-32 w-full items-center justify-center">
      <motion.div
        className="glass-subtle absolute flex h-20 w-28 -rotate-6 flex-col gap-1.5 rounded-lg p-3"
        initial={{ y: 6 }}
        animate={{ y: [6, 2, 6] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
      >
        <div className="h-1.5 w-3/4 rounded-full bg-foreground/15" />
        <div className="h-1.5 w-full rounded-full bg-foreground/10" />
        <div className="h-1.5 w-2/3 rounded-full bg-foreground/10" />
      </motion.div>
      <motion.div
        className="glass relative z-10 flex h-24 w-32 flex-col gap-2 rounded-lg p-3 shadow-lg"
        initial={{ y: -4, rotate: 3 }}
        animate={{ y: [-4, 0, -4], rotate: [3, 5, 3] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
      >
        <div className="flex items-center gap-1.5">
          <FileText className="h-3 w-3 text-primary" />
          <div className="h-1.5 w-16 rounded-full bg-foreground/25" />
        </div>
        <div className="h-1.5 w-full rounded-full bg-foreground/15" />
        <div className="h-1.5 w-4/5 rounded-full bg-foreground/15" />
        <div className="h-1.5 w-3/5 rounded-full bg-foreground/15" />
      </motion.div>
    </div>
  )
}
