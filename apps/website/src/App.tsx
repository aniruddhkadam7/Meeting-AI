import { Routes, Route } from "react-router-dom"
import { PurchaseFlowDialog } from "@/components/blocks/purchase-flow-dialog"
import { GlassFilter } from "@/components/ui/liquid-glass-button"
import { Nav } from "@/components/sections/nav"
import { Footer } from "@/components/sections/footer"
import { LandingPage } from "@/pages/landing-page"
import { DownloadPage } from "@/pages/download-page"
import { PurchaseFlowProvider } from "@/lib/purchase-flow"

function App() {
  return (
    <PurchaseFlowProvider>
      <div id="top" className="relative">
        <GlassFilter />
        <Nav />
        <main>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/download" element={<DownloadPage />} />
          </Routes>
        </main>
        <Footer />
        <PurchaseFlowDialog />
      </div>
    </PurchaseFlowProvider>
  )
}

export default App
