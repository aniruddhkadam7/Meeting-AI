import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { GlassFilter } from "@/components/ui/liquid-glass-button";
import { Nav } from "@/components/sections/nav";
import { Footer } from "@/components/sections/footer";
import { PurchaseFlowDialog } from "@/components/blocks/purchase-flow-dialog";
import { PurchaseFlowProvider } from "@/lib/purchase-flow";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Smallbird — AI assistant for important conversations",
  description:
    "Smallbird gives you real-time AI assistance during interviews and meetings — with context from your CV, job description, and meeting documents.",
  icons: {
    icon: "/smallbird-logo.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="light"
      style={{ colorScheme: "light" }}
      className={`${geistSans.variable} ${geistMono.variable} antialiased`}
    >
      <body>
        <PurchaseFlowProvider>
          <div id="top" className="relative">
            <GlassFilter />
            <Nav />
            <main>{children}</main>
            <Footer />
            <PurchaseFlowDialog />
          </div>
        </PurchaseFlowProvider>
      </body>
    </html>
  );
}
