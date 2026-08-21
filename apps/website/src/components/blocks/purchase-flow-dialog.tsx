"use client"

import { useState } from "react"
import { CheckCircle2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { LiquidButton } from "@/components/ui/liquid-glass-button"
import { PLAN_LABELS, usePurchaseFlow } from "@/lib/purchase-flow"

const PLAN_PRICE_SUMMARY: Record<string, string> = {
  free: "₹0 — no payment needed",
  "interview-pass": "₹299 one-time",
  "pro-monthly": "₹799 / month",
  "pro-annual": "₹5,999 / year",
}

export function PurchaseFlowDialog() {
  const { activeFlow, closeFlow, completeSignup, completePayment } = usePurchaseFlow()
  const [email, setEmail] = useState("")

  if (!activeFlow) return null

  const planLabel = PLAN_LABELS[activeFlow.plan]
  const priceSummary = PLAN_PRICE_SUMMARY[activeFlow.plan]

  return (
    <Dialog open onOpenChange={(open) => !open && closeFlow()}>
      <DialogContent className="sm:max-w-md">
        {activeFlow.step === "signup" ? (
          <>
            <DialogHeader>
              <DialogTitle>Create your account</DialogTitle>
              <DialogDescription>
                Signing up for <span className="font-medium text-foreground">{planLabel}</span>{" "}
                ({priceSummary}).
              </DialogDescription>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                completeSignup(email)
              }}
            >
              <div className="space-y-1.5">
                <label htmlFor="signup-email" className="text-sm font-medium text-foreground">
                  Email address
                </label>
                <input
                  id="signup-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                />
                <p className="text-xs text-muted-foreground">
                  This is a UI preview — no account is actually created yet.
                </p>
              </div>
              <DialogFooter>
                <LiquidButton type="submit" className="w-full">
                  Continue
                </LiquidButton>
              </DialogFooter>
            </form>
          </>
        ) : null}

        {activeFlow.step === "payment" ? (
          <>
            <DialogHeader>
              <DialogTitle>Payment</DialogTitle>
              <DialogDescription>
                {planLabel} — {priceSummary}
              </DialogDescription>
            </DialogHeader>
            <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
              Payment provider isn't connected yet. In the real flow this is
              where you'd complete checkout (e.g. via Razorpay for INR).
            </div>
            <DialogFooter>
              <LiquidButton className="w-full" onClick={completePayment}>
                Simulate successful payment
              </LiquidButton>
            </DialogFooter>
          </>
        ) : null}

        {activeFlow.step === "done" ? (
          <>
            <DialogHeader>
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-foreground/5">
                <CheckCircle2 className="h-6 w-6 text-foreground" />
              </div>
              <DialogTitle className="text-center">You're all set</DialogTitle>
              <DialogDescription className="text-center">
                {planLabel} is ready. Download Smallbird for Windows to get
                started.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <LiquidButton className="w-full" onClick={closeFlow}>
                Go to download
              </LiquidButton>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
