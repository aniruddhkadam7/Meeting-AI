import logo from "@/assets/smallbird-logo.png"

const columns = [
  {
    title: "Product",
    links: [
      { label: "Interview Mode", href: "/#modes" },
      { label: "Meeting Mode", href: "/#modes" },
      { label: "How it works", href: "/#product-demo" },
      { label: "Download for Windows", href: "/download" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "Pricing", href: "/#pricing" },
      { label: "Security", href: "/#security" },
      { label: "Privacy", href: "/#privacy" },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Terms", href: "#terms" },
      { label: "Contact", href: "mailto:hello@smallbird.app" },
    ],
  },
]

export function Footer() {
  return (
    <footer className="border-t border-border py-16 px-4">
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-10 sm:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <div>
            <img src={logo} alt="Smallbird" className="h-8 w-auto" />
            <p className="mt-3 max-w-xs text-sm text-muted-foreground">
              AI assistance for important conversations.
            </p>
          </div>
          {columns.map((col) => (
            <div key={col.title}>
              <h3 className="text-sm font-medium text-foreground">{col.title}</h3>
              <ul className="mt-3 space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 border-t border-border pt-6 text-sm text-muted-foreground">
          © {new Date().getFullYear()} Smallbird. All rights reserved.
        </div>
      </div>
    </footer>
  )
}
