import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { NavUser } from "@/components/nav-user";
import { Footer } from "@/components/footer";
import { Toaster } from "@/components/ui/toaster";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "RAG Platform",
  description: "Pipeline-as-a-Service for documents",
};

// Skip static prerender — every page hits the FastAPI backend at runtime.
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <div className="flex flex-col min-h-screen bg-background">
            <nav className="border-b px-6 py-3 flex items-center gap-6">
              <a href="/" className="font-semibold text-lg hover:text-foreground/80">
                RAG Platform
              </a>
              <a href="/" className="text-sm text-muted-foreground hover:text-foreground">
                Dashboard
              </a>
              <a href="/pipelines" className="text-sm text-muted-foreground hover:text-foreground">
                Pipelines
              </a>
              <a href="/experiments" className="text-sm text-muted-foreground hover:text-foreground">
                Experiments
              </a>
              <a href="/datasets" className="text-sm text-muted-foreground hover:text-foreground">
                Datasets
              </a>
              <a href="/runs" className="text-sm text-muted-foreground hover:text-foreground">
                Runs
              </a>
              <a href="/docs" className="text-sm text-muted-foreground hover:text-foreground">
                Docs
              </a>
              <a href="/pricing" className="text-sm text-muted-foreground hover:text-foreground">
                Тарифы
              </a>
              <NavUser />
            </nav>
            <main className="flex-1 px-6 py-6">{children}</main>
            <Footer />
          </div>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
