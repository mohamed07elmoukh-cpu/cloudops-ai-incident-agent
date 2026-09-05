import type { Metadata } from "next";

import { MobileNavigation, Sidebar, Topbar } from "@/components/navigation";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "CloudOps Control Center",
  description: "Supervision et gestion des incidents CloudOps",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
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
