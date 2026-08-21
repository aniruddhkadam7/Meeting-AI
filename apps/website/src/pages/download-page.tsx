import { Link } from "react-router-dom"
import { ArrowLeft, Monitor, Apple, Download } from "lucide-react"
import { LiquidButton } from "@/components/ui/liquid-glass-button"
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card"
import { PLAN_LABELS, usePurchaseFlow } from "@/lib/purchase-flow"

export function DownloadPage() {
  const { canDownload, selectedPlan, startFlow } = usePurchaseFlow()

  return (
    <div className="mx-auto max-w-3xl px-4 py-16 sm:py-24">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Smallbird
      </Link>

      <div className="mt-10 text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Download Smallbird
        </h1>
        <p className="mt-4 text-muted-foreground">
          {canDownload
            ? `${PLAN_LABELS[selectedPlan!]} plan ready — pick your platform below.`
            : "Sign in for free, then download and install the desktop app."}
        </p>
      </div>

      <div className="mt-12 grid gap-6 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border">
              <Monitor className="h-5 w-5 text-foreground" />
            </div>
            <CardTitle className="text-lg">Windows</CardTitle>
            <CardDescription>Windows 10 and 11, 64-bit.</CardDescription>
          </CardHeader>
          <CardContent />
          <CardFooter>
            <LiquidButton
              className="w-full"
              onClick={() => {
                if (canDownload) {
                  // TODO: point at the real Windows installer artifact once release builds are published.
                  window.location.href = "/download"
                } else {
                  startFlow("free")
                }
              }}
            >
              <Download className="h-4 w-4" />
              Download for Windows
            </LiquidButton>
          </CardFooter>
        </Card>

        <Card className="opacity-70">
          <CardHeader>
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border">
              <Apple className="h-5 w-5 text-foreground" />
            </div>
            <CardTitle className="text-lg">Mac</CardTitle>
            <CardDescription>Coming soon.</CardDescription>
          </CardHeader>
          <CardContent />
          <CardFooter>
            <LiquidButton className="w-full" variant="outline" disabled>
              <Apple className="h-4 w-4" />
              Coming soon
            </LiquidButton>
          </CardFooter>
        </Card>
      </div>

      <p className="mt-10 text-center text-xs text-muted-foreground">
        After installing, sign in with the email you signed up with to start
        your first session.
      </p>
    </div>
  )
}
