import { motion } from "motion/react"
import { Check } from "lucide-react"
import { LiquidButton } from "@/components/ui/liquid-glass-button"
import { Badge } from "@/components/ui/badge"
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { usePurchaseFlow, type PlanId } from "@/lib/purchase-flow"

type Plan = {
  id: PlanId
  name: string
  price: string
  cadence: string
  billingNote: string
  description: string
  features: string[]
  cta: string
  recommended?: boolean
}

const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: "₹0",
    cadence: "",
    billingNote: "No card required",
    description: "Limited usage, suitable for trying Smallbird.",
    features: ["Limited monthly usage", "Interview Mode", "Meeting Mode", "Basic context upload"],
    cta: "Start Free",
  },
  {
    id: "interview-pass",
    name: "Interview Pass",
    price: "₹299",
    cadence: "one-time",
    billingNote: "2 hours of Interview Mode",
    description: "A one-time pass for a single high-stakes interview.",
    features: ["2 hours of Interview Mode", "CV + JD context", "Real-time AI assistance", "Valid until used"],
    cta: "Get Interview Pass",
  },
  {
    id: "pro-monthly",
    name: "Pro Monthly",
    price: "₹799",
    cadence: "/ month",
    billingNote: "Billed monthly",
    description: "Full Interview + Meeting assistance with generous usage.",
    features: ["Interview + Meeting Mode", "Generous monthly usage", "Full context library", "Priority support"],
    cta: "Start Pro",
  },
  {
    id: "pro-annual",
    name: "Pro Annual",
    price: "₹5,999",
    cadence: "/ year",
    billingNote: "Billed yearly · best value",
    description: "Same Pro features as monthly, at the best price.",
    features: ["Interview + Meeting Mode", "Generous monthly usage", "Full context library", "Priority support"],
    cta: "Get Pro Annual",
    recommended: true,
  },
]

export function Pricing() {
  const { startFlow } = usePurchaseFlow()

  return (
    <section id="pricing" className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Simple, transparent pricing
          </h2>
          <p className="mt-4 text-muted-foreground">
            Priced for India. One-time, monthly, or yearly — pick what fits
            how often you use Smallbird.
          </p>
        </div>

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan, i) => (
            <motion.div
              key={plan.id}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5, delay: i * 0.08, ease: "easeOut" }}
              className="relative h-full"
            >
              {plan.recommended ? (
                <Badge className="absolute -top-3 left-1/2 z-20 -translate-x-1/2">
                  Recommended
                </Badge>
              ) : null}

              <Card
                className={cn(
                  "h-full transition-all duration-300 hover:-translate-y-1 hover:shadow-lg",
                  plan.recommended && "shadow-md",
                )}
              >
                <CardHeader>
                  <CardTitle className="text-lg">{plan.name}</CardTitle>
                  <div className="mt-2 flex items-baseline gap-1.5">
                    <span className="text-3xl font-semibold tracking-tight">
                      {plan.price}
                    </span>
                    {plan.cadence ? (
                      <span className="text-sm text-muted-foreground">{plan.cadence}</span>
                    ) : null}
                  </div>
                  <p className="text-xs font-medium text-muted-foreground">{plan.billingNote}</p>
                  <CardDescription>{plan.description}</CardDescription>
                </CardHeader>
                <CardContent className="flex-1">
                  <ul className="space-y-2.5 text-sm">
                    {plan.features.map((f) => (
                      <li key={f} className="flex items-start gap-2">
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-foreground" />
                        <span className="text-muted-foreground">{f}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
                <CardFooter>
                  <LiquidButton
                    className="w-full"
                    variant={plan.recommended ? "default" : "outline"}
                    onClick={() => startFlow(plan.id)}
                  >
                    {plan.cta}
                  </LiquidButton>
                </CardFooter>
              </Card>
            </motion.div>
          ))}
        </div>

        <p className="mt-8 text-center text-xs text-muted-foreground">
          Prices are in INR and include applicable taxes. The Interview Pass
          is a one-time purchase; Pro Monthly and Pro Annual are recurring
          subscriptions.
        </p>
      </div>
    </section>
  )
}
