import { useState } from "react"
import { SegmentedToggle } from "@/components/ui/segmented-toggle"
import { AppMockupInterview } from "@/components/blocks/app-mockup-interview"
import { AppMockupMeeting } from "@/components/blocks/app-mockup-meeting"

const interviewSteps = [
  { title: "Start the session", detail: "Select Interview Mode and hit Start." },
  { title: "Smallbird listens", detail: "It follows the conversation as it happens." },
  { title: "Context is ready", detail: "Your CV and the job description are already loaded in." },
  { title: "Get a relevant answer", detail: "When a question comes in, Smallbird surfaces a response." },
]

const meetingSteps = [
  { title: "Start the session", detail: "Select Meeting Mode and hit Start." },
  { title: "Smallbird listens", detail: "It follows the conversation as it happens." },
  { title: "Context is ready", detail: "Your meeting documents are already loaded in." },
  { title: "Get relevant context", detail: "Smallbird surfaces what matters, in real time." },
]

const modeOptions = [
  { value: "interview", label: "Interview Mode" },
  { value: "meeting", label: "Meeting Mode" },
]

export function ProductDemo() {
  const [mode, setMode] = useState("interview")

  return (
    <section id="product-demo" className="border-t border-border py-20 px-4 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            See how Smallbird works
          </h2>
          <p className="mt-4 text-muted-foreground">
            One workflow, two modes. Start a session, and Smallbird listens,
            understands, and assists — in real time.
          </p>
        </div>

        <div className="mt-10 flex justify-center">
          <SegmentedToggle options={modeOptions} value={mode} onChange={setMode} />
        </div>

        <div className="mt-10">
          {mode === "interview" ? (
            <DemoLayout steps={interviewSteps} mockup={<AppMockupInterview />} />
          ) : (
            <DemoLayout steps={meetingSteps} mockup={<AppMockupMeeting />} />
          )}
        </div>
      </div>
    </section>
  )
}

function DemoLayout({
  steps,
  mockup,
}: {
  steps: { title: string; detail: string }[]
  mockup: React.ReactNode
}) {
  return (
    <div className="grid gap-12 lg:grid-cols-[0.85fr_1.4fr] lg:items-center">
      <div className="space-y-7">
        {steps.map((step, i) => (
          <div key={step.title} className="flex gap-4">
            <span className="text-2xl font-semibold tabular-nums text-foreground/25">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <p className="font-medium text-foreground">{step.title}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{step.detail}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="shadow-[0_0_60px_-20px_rgba(0,0,0,0.25)] dark:shadow-[0_0_60px_-20px_rgba(255,255,255,0.08)] rounded-xl">
        {mockup}
      </div>
    </div>
  )
}
