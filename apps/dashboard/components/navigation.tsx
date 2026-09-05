"use client";

import {
  Activity,
  Bell,
  ChevronDown,
  CircleHelp,
  CloudCog,
  Command,
  LayoutDashboard,
  ListChecks,
  Search,
  ServerCog,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Vue d’ensemble", icon: LayoutDashboard },
  { href: "/incidents", label: "Incidents", icon: ListChecks },
  { href: "/system", label: "Santé du système", icon: ServerCog },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === href : pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="CloudOps accueil">
        <span className="brand-mark"><CloudCog size={21} strokeWidth={2} /></span>
        <span><strong>CloudOps</strong><small>Incident control</small></span>
      </Link>

      <div className="workspace-switcher" aria-label="Espace de travail actif">
        <span className="workspace-avatar">P</span>
        <span><small>Projet</small><strong>production-core</strong></span>
        <ChevronDown size={14} />
      </div>

      <nav className="side-nav" aria-label="Navigation principale">
        <p className="nav-label">Opérations</p>
        {links.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className={isActive(pathname, href) ? "active" : ""}>
            <Icon size={18} strokeWidth={1.9} />
            <span>{label}</span>
          </Link>
        ))}
        <p className="nav-label nav-label-spaced">Automatisation</p>
        <span className="nav-static"><ShieldCheck size={18} /><span>Politiques</span><span className="nav-count">4</span></span>
        <span className="nav-static"><Command size={18} /><span>Runbooks</span><span className="nav-count">5</span></span>
      </nav>

      <div className="sidebar-status">
        <span className="status-dot" />
        <div><strong>Agent opérationnel</strong><small>4 moteurs de remédiation prêts</small></div>
      </div>
    </aside>
  );
}

export function MobileNavigation() {
  const pathname = usePathname();
  return (
    <nav className="mobile-nav" aria-label="Navigation mobile">
      {links.map(({ href, label, icon: Icon }) => (
        <Link key={href} href={href} className={isActive(pathname, href) ? "active" : ""}>
          <Icon size={19} /><span>{label}</span>
        </Link>
      ))}
    </nav>
  );
}

export function Topbar() {
  return (
    <header className="topbar">
      <div className="mobile-brand"><Activity size={20} /><strong>CloudOps</strong></div>
      <label className="global-search">
        <Search size={17} />
        <input aria-label="Rechercher dans CloudOps" placeholder="Rechercher un incident, une ressource…" />
        <kbd>⌘ K</kbd>
      </label>
      <div className="topbar-actions">
        <span className="environment-pill"><span className="status-dot" />Production</span>
        <button className="topbar-button" aria-label="Aide"><CircleHelp size={18} /></button>
        <button className="topbar-button notification-button" aria-label="Notifications"><Bell size={18} /><span /></button>
        <span className="user-avatar" aria-label="Profil de l’opérateur">MO</span>
      </div>
    </header>
  );
}
