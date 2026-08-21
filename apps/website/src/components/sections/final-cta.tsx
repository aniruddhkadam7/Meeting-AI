import { LiquidButton } from "@/components/ui/liquid-glass-button"

export function FinalCta() {
  return (
    <section id="get-started" className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Make every important conversation smarter.
        </h2>
        <div className="mt-8 flex justify-center">
          <LiquidButton
            size="lg"
            onClick={() => {
              window.location.href = "#pricing"
            }}
          >
            Get Started
          </LiquidButton>
        </div>
      </div>
    </section>
  )
}
