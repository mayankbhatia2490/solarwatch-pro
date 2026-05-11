import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "SolarWatch Pro",
  description: "Premium solar monitoring dashboard",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.className}`} suppressHydrationWarning>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
          <div className="flex min-h-screen" suppressHydrationWarning>
            <Sidebar />
            <main className="flex-1 lg:ml-64 p-4 lg:p-6 pb-24 lg:pb-6" suppressHydrationWarning>
              {children}
            </main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
