import { useNavigate } from "react-router-dom"
import { Download } from "lucide-react"
import logo from "@/assets/smallbird-logo.png"
import { LiquidButton } from "@/components/ui/liquid-glass-button"
import { LiquidGlassContainer } from "@/components/ui/liquid-glass-container"

const links = [
  { label: "Product", href: "/#product-demo" },
  { label: "Modes", href: "/#modes" },
  { label: "Pricing", href: "/#pricing" },
  { label: "Privacy", href: "/#privacy" },
]

export function Nav() {
  const navigate = useNavigate()

  return (
    <header className="sticky top-4 z-50 flex justify-center px-4">
      <LiquidGlassContainer className="w-full max-w-5xl">
        <div className="flex h-16 w-full items-center justify-between gap-4 px-4">
          <a href="/" className="flex items-center gap-2">
            <img src={logo} alt="Smallbird" className="h-6 w-auto" />
          </a>
          <nav className="hidden items-center gap-8 sm:flex">
            {links.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="text-sm font-medium text-foreground/80 transition-colors hover:text-foreground"
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <LiquidButton size="sm" variant="outline" onClick={() => navigate("/download")}>
              <Download className="h-3.5 w-3.5" />
              Download
            </LiquidButton>
            <LiquidButton
              size="sm"
              onClick={() => {
                window.location.href = "/#pricing"
              }}
            >
              Get Started
            </LiquidButton>
          </div>
        </div>
      </LiquidGlassContainer>
    </header>
  )
}
