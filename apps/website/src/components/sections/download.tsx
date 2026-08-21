"use client"

import { useRouter } from "next/navigation"
import { Download } from "lucide-react"
import { LiquidButton } from "@/components/ui/liquid-glass-button"

export function DownloadSection() {
  const router = useRouter()

  return (
    <section id="download" className="scroll-mt-16 border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Download Smallbird for Windows
        </h2>
        <p className="mt-4 text-muted-foreground">
          Sign in for free, download the desktop app, install it, and start
          your first session.
        </p>

        <div className="mt-8 flex justify-center">
          <LiquidButton size="xl" onClick={() => router.push("/download")}>
            <Download className="h-4 w-4" />
            Get the Windows app
          </LiquidButton>
        </div>
      </div>
    </section>
  )
}
