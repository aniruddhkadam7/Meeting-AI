import { createContext, useContext, useState, type ReactNode } from "react"

export type PlanId = "free" | "interview-pass" | "pro-monthly" | "pro-annual"

export const PLAN_LABELS: Record<PlanId, string> = {
  free: "Free",
  "interview-pass": "Interview Pass",
  "pro-monthly": "Pro Monthly",
  "pro-annual": "Pro Annual",
}

// Plans that cost money and require the mock "payment" step before download
// unlocks. Free skips straight from signup to ready-to-download.
const PAID_PLANS = new Set<PlanId>(["interview-pass", "pro-monthly", "pro-annual"])

export type FlowStep = "signup" | "payment" | "done"

interface PurchaseFlowState {
  signedUp: boolean
  selectedPlan: PlanId | null
  purchased: boolean
  canDownload: boolean
  activeFlow: { plan: PlanId; step: FlowStep } | null
  startFlow: (plan: PlanId) => void
  completeSignup: (email: string) => void
  completePayment: () => void
  closeFlow: () => void
  reset: () => void
}

const PurchaseFlowContext = createContext<PurchaseFlowState | null>(null)

export function PurchaseFlowProvider({ children }: { children: ReactNode }) {
  const [signedUp, setSignedUp] = useState(false)
  const [selectedPlan, setSelectedPlan] = useState<PlanId | null>(null)
  const [purchased, setPurchased] = useState(false)
  const [activeFlow, setActiveFlow] = useState<{ plan: PlanId; step: FlowStep } | null>(null)

  const startFlow = (plan: PlanId) => {
    setActiveFlow({ plan, step: "signup" })
  }

  const completeSignup = (_email: string) => {
    // TODO: replace with real auth (e.g. Supabase/Clerk sign-up call).
    setSignedUp(true)
    if (!activeFlow) return
    setSelectedPlan(activeFlow.plan)
    if (PAID_PLANS.has(activeFlow.plan)) {
      setActiveFlow({ plan: activeFlow.plan, step: "payment" })
    } else {
      setPurchased(true)
      setActiveFlow({ plan: activeFlow.plan, step: "done" })
    }
  }

  const completePayment = () => {
    // TODO: replace with real payment flow (e.g. Razorpay for INR pricing).
    setPurchased(true)
    if (!activeFlow) return
    setActiveFlow({ plan: activeFlow.plan, step: "done" })
  }

  const closeFlow = () => setActiveFlow(null)

  const reset = () => {
    setSignedUp(false)
    setSelectedPlan(null)
    setPurchased(false)
    setActiveFlow(null)
  }

  const canDownload = signedUp && (selectedPlan === "free" || purchased)

  return (
    <PurchaseFlowContext.Provider
      value={{
        signedUp,
        selectedPlan,
        purchased,
        canDownload,
        activeFlow,
        startFlow,
        completeSignup,
        completePayment,
        closeFlow,
        reset,
      }}
    >
      {children}
    </PurchaseFlowContext.Provider>
  )
}

export function usePurchaseFlow() {
  const ctx = useContext(PurchaseFlowContext)
  if (!ctx) {
    throw new Error("usePurchaseFlow must be used within a PurchaseFlowProvider")
  }
  return ctx
}
