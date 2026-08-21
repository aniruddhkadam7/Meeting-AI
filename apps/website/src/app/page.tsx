import { HeroWithMockup } from "@/components/blocks/hero-with-mockup";
import { HeroGlassOverlay } from "@/components/blocks/hero-glass-overlay";
import { ProductDemo } from "@/components/sections/product-demo";
import { TwoModes } from "@/components/sections/two-modes";
import { HowItWorks } from "@/components/sections/how-it-works";
import { Advantages } from "@/components/sections/advantages";
import { Privacy } from "@/components/sections/privacy";
import { Pricing } from "@/components/sections/pricing";
import { DownloadSection } from "@/components/sections/download";
import { FinalCta } from "@/components/sections/final-cta";

export default function Home() {
  return (
    <>
      <HeroWithMockup
        eyebrow="AI assistance for important conversations"
        title="Real-time AI assistance, right when the conversation matters."
        description="Smallbird listens, understands your context, and helps you respond well — in interviews and meetings alike."
        mockup={<HeroGlassOverlay />}
      />
      <ProductDemo />
      <TwoModes />
      <HowItWorks />
      <Advantages />
      <Privacy />
      <Pricing />
      <DownloadSection />
      <FinalCta />
    </>
  );
}
