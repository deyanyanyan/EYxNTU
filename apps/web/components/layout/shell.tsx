"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, BookOpenText, FolderKanban, LogOut, Moon, Settings2, Sun, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";
import { useTheme } from "@/hooks/use-theme";
import { clearSession } from "@/lib/auth";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }>; roles: string[] };

const NAV: NavItem[] = [
  { href: "/projects", label: "Projects", icon: FolderKanban, roles: ["admin", "instructor"] },
  { href: "/jobs", label: "Jobs", icon: Activity, roles: ["admin", "instructor"] },
  { href: "/learn", label: "Learn", icon: BookOpenText, roles: ["admin", "instructor", "learner"] },
  { href: "/admin/users", label: "Users", icon: Users, roles: ["admin"] },
  { href: "/admin/prompts", label: "Prompts", icon: Settings2, roles: ["admin"] },
];

/**
 * Workbench shell: a narrow icon rail on the left and a slim top bar.
 * Pages render into the remaining area and may add their own inspector pane.
 */
export function Shell({ children, title, actions }: { children: React.ReactNode; title?: React.ReactNode; actions?: React.ReactNode }) {
  const { user } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const items = NAV.filter((n) => user && n.roles.includes(user.role));

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <aside className="pane flex w-14 flex-col items-center border-r py-3">
        <Link href="/projects" className="mb-4 flex size-8 items-center justify-center rounded-md bg-accent font-mono text-sm font-bold text-accent-foreground" title="LMS Studio">
          L
        </Link>
        <nav className="flex flex-1 flex-col gap-1">
          {items.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              title={label}
              className={cn("flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground", pathname.startsWith(href) && "bg-accent-soft text-foreground")}
            >
              <Icon className="size-4" />
            </Link>
          ))}
        </nav>
        <Button variant="ghost" size="icon" onClick={toggle} title="Toggle theme">
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          title="Sign out"
          onClick={() => {
            clearSession();
            router.push("/login");
          }}
        >
          <LogOut />
        </Button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="pane flex h-11 shrink-0 items-center justify-between border-b px-4">
          <div className="min-w-0 truncate text-sm font-medium">{title}</div>
          <div className="flex items-center gap-2">
            {actions}
            {user && (
              <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">
                {user.name} <span className="font-mono opacity-70">· {user.role}</span>
              </span>
            )}
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
