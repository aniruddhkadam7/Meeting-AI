"use client"

import { motion } from "motion/react"
import { cn } from "@/lib/utils"

interface SegmentedToggleOption {
  value: string
  label: string
}

interface SegmentedToggleProps {
  options: SegmentedToggleOption[]
  value: string
  onChange: (value: string) => void
  className?: string
}

export function SegmentedToggle({ options, value, onChange, className }: SegmentedToggleProps) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 p-1",
        className,
      )}
    >
      {options.map((option) => {
        const isActive = option.value === value
        return (
          <button
            key={option.value}
            role="tab"
            type="button"
            aria-selected={isActive}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative rounded-full px-5 py-2 text-sm font-medium transition-colors",
              isActive ? "text-primary-foreground" : "text-foreground/70 hover:text-foreground",
            )}
          >
            {isActive ? (
              <motion.span
                layoutId="segmented-toggle-active"
                className="absolute inset-0 rounded-full bg-primary"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            ) : null}
            <span className="relative z-10">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
