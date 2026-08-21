import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Glow } from "@/components/ui/glow"
import { LiquidButton } from "@/components/ui/liquid-glass-button"

interface HeroWithMockupProps {
  eyebrow?: string
  title: string
  description: string
  primaryCta?: {
    text: string
    href: string
  }
  secondaryCta?: {
    text: string
    href: string
  }
  mockup: ReactNode
  className?: string
}

export function HeroWithMockup({
  eyebrow,
  title,
  description,
  primaryCta = { text: "Get Started", href: "#get-started" },
  secondaryCta = { text: "See how it works", href: "#product-demo" },
  mockup,
  className,
}: HeroWithMockupProps) {
  return (
    <section
      className={cn(
        "relative bg-background text-foreground",
        "py-16 px-4 md:py-24 lg:py-28",
        "overflow-hidden",
        className,
      )}
    >
      <div className="relative mx-auto flex max-w-5xl flex-col gap-12 lg:gap-20">
        <div className="relative z-10 flex flex-col items-center gap-6 text-center lg:gap-8">
          {eyebrow ? (
            <Badge
              variant="outline"
              className="animate-appear px-3 py-1 text-xs tracking-wide text-muted-foreground opacity-0 [animation-delay:0ms]"
            >
              {eyebrow}
            </Badge>
          ) : null}

          <h1
            className={cn(
              "inline-block animate-appear opacity-0 [animation-delay:80ms]",
              "text-4xl font-semibold tracking-tight sm:text-5xl md:text-6xl",
              "leading-[1.1]",
              "text-foreground",
            )}
          >
            {title}
          </h1>

          <p
            className={cn(
              "max-w-[620px] animate-appear opacity-0 [animation-delay:200ms]",
              "text-base sm:text-lg",
              "text-muted-foreground",
            )}
          >
            {description}
          </p>

          <div className="relative z-10 flex flex-wrap items-center justify-center gap-4 animate-appear opacity-0 [animation-delay:320ms]">
            <LiquidButton
              size="lg"
              onClick={() => {
                window.location.href = primaryCta.href
              }}
            >
              {primaryCta.text}
            </LiquidButton>
            <LiquidButton
              size="lg"
              variant="outline"
              onClick={() => {
                window.location.href = secondaryCta.href
              }}
            >
              {secondaryCta.text}
            </LiquidButton>
          </div>

          <div className="animate-appear relative w-full max-w-3xl pt-10 opacity-0 [animation-delay:480ms]">
            {mockup}
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <Glow variant="above" className="opacity-60" />
      </div>
    </section>
  )
}
