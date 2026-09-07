import type { Metadata } from "next";
import { Montserrat } from "next/font/google";

import { MobileNavigation, Sidebar, Topbar } from "@/components/navigation";

import "./globals.css";
import { Providers } from "./providers";

const montserrat = Montserrat({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-montserrat",
});

export const metadata: Metadata = {
  title: "CloudOps Control Center",
  description: "Supervision et gestion des incidents CloudOps",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr" className={montserrat.variable}>
      <body>
        <Providers>
          <div className="app-shell">
            <Sidebar />
            <div className="main-column">
              <Topbar />
              <main className="page-container">{children}</main>
            </div>
            <MobileNavigation />
          </div>
        </Providers>
      </body>
    </html>
  );
}
