import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { NavUser } from "@/components/nav-user";
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
          <div className="min-h-screen bg-background">
            <nav className="border-b px-6 py-3 flex items-center gap-6">
              <span className="font-semibold text-lg">RAG Platform</span>
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
              <a href="/docs" className="text-sm text-muted-foreground hover:text-foreground">
                Docs
              </a>
              <NavUser />
            </nav>
            <main className="px-6 py-6">{children}</main>
          </div>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
