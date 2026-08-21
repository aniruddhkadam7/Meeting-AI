"use client"

import { motion } from "motion/react"
import { FileText, Check, X } from "lucide-react"
import { cn } from "@/lib/utils"

const items = [
  { label: "CV / Resume", included: true },
  { label: "Job Description", included: true },
  { label: "Random Document", included: false },
]

export function UploadControlIllustration() {
  return (
    <div className="glass-subtle flex w-full max-w-xs flex-col gap-2 rounded-lg p-4">
      {items.map((item, i) => (
        <motion.div
          key={item.label}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, delay: i * 0.15 }}
          className={cn(
            "flex items-center justify-between rounded-md border px-3 py-2",
            item.included
              ? "border-emerald-600/20 bg-emerald-600/5"
              : "border-border bg-muted/40",
          )}
        >
          <div className="flex items-center gap-2">
            <FileText className={cn("h-3.5 w-3.5", item.included ? "text-foreground" : "text-muted-foreground")} />
            <span className={cn("text-xs font-medium", item.included ? "text-foreground" : "text-muted-foreground")}>
              {item.label}
            </span>
          </div>
          {item.included ? (
            <Check className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <X className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </motion.div>
      ))}
    </div>
  )
}
