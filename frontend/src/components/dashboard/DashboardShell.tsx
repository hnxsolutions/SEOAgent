'use client';

import {
  Activity,
  Bot,
  Camera,
  Database,
  FileCheck2,
  FileText,
  FileWarning,
  GitBranch,
  LayoutDashboard,
  LineChart,
  Newspaper,
  Rocket,
  Search,
  SearchCheck,
  Target,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '@/lib/dashboard-api';
import { cn } from '@/lib/utils';
import type { Project, UUID } from '@/types/dashboard';
import { EmptyState, ErrorState } from '@/components/dashboard/DashboardStates';

type DashboardProjectContextValue = {
  projectId?: UUID;
  project?: Project;
  projects: Project[];
  setProjectId: (_projectId: UUID) => void;
  isLoading: boolean;
};

const DashboardProjectContext = createContext<DashboardProjectContextValue | null>(null);

export function useDashboardProject() {
  const value = useContext(DashboardProjectContext);
  if (!value) {
    throw new Error('useDashboardProject must be used inside DashboardShell');
  }
  return value;
}

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [projectId, setProjectIdState] = useState<UUID | undefined>();

  const projectsQuery = useQuery({
    queryKey: ['dashboard-projects'],
    queryFn: dashboardApi.listProjects,
    retry: false,
  });

  useEffect(() => {
    if (!projectsQuery.data?.length) return;
    const stored = window.localStorage.getItem('dashboard_project_id');
    const storedProject = projectsQuery.data.find((project) => project.id === stored);
    setProjectIdState((current) => current ?? storedProject?.id ?? projectsQuery.data[0]?.id);
  }, [projectsQuery.data]);

  const setProjectId = (nextProjectId: UUID) => {
    window.localStorage.setItem('dashboard_project_id', nextProjectId);
    setProjectIdState(nextProjectId);
  };

  const project = useMemo(
    () => projectsQuery.data?.find((item) => item.id === projectId),
    [projectsQuery.data, projectId]
  );

  return (
    <DashboardProjectContext.Provider
      value={{
        projectId,
        project,
        projects: projectsQuery.data ?? [],
        setProjectId,
        isLoading: projectsQuery.isLoading,
      }}
    >
      <div className="min-h-screen bg-slate-50">
        <aside className="fixed inset-y-0 left-0 hidden w-72 border-r bg-white lg:block">
          <div className="flex h-16 items-center border-b px-6">
            <div>
              <p className="text-sm font-semibold text-slate-900">AI SEO Agent</p>
              <p className="text-xs text-muted-foreground">Approval Console</p>
            </div>
          </div>
          <nav className="space-y-1 px-3 py-4">
            {navItems.map((item) => {
              const active =
                item.href === '/dashboard'
                  ? pathname === item.href
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950',
                    active && 'bg-blue-50 text-blue-700'
                  )}
                >
                  <item.icon className="h-4 w-4" aria-hidden="true" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="lg:pl-72">
          <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
            <div className="flex min-h-16 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Dashboard
                </p>
                <h1 className="text-xl font-semibold text-slate-950">
                  {project?.name ?? 'Project workspace'}
                </h1>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex gap-1 overflow-x-auto rounded-md border bg-white p-1 lg:hidden">
                  {navItems.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        'flex h-9 w-9 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100',
                        (item.href === '/dashboard'
                          ? pathname === item.href
                          : pathname.startsWith(item.href)) && 'bg-blue-50 text-blue-700'
                      )}
                      title={item.label}
                    >
                      <item.icon className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  ))}
                </div>
                <select
                  className="h-10 min-w-56 rounded-md border bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  value={projectId ?? ''}
                  onChange={(event) => setProjectId(event.target.value)}
                  disabled={projectsQuery.isLoading || !projectsQuery.data?.length}
                  aria-label="Select project"
                >
                  {!projectId ? <option value="">Select project</option> : null}
                  {(projectsQuery.data ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <Link
                  href="/dashboard/setup"
                  className="inline-flex h-10 items-center justify-center rounded-md border bg-white px-3 text-sm font-medium shadow-sm transition-colors hover:bg-slate-50"
                >
                  <Rocket className="mr-2 h-4 w-4" aria-hidden="true" />
                  Setup
                </Link>
              </div>
            </div>
          </header>

          <main className="px-4 py-6 sm:px-6 lg:px-8">
            {projectsQuery.isError ? (
              <ErrorState
                title="Projects could not load"
                message="Check that the backend is running and that your session token is valid."
                onRetry={() => void projectsQuery.refetch()}
              />
            ) : !projectsQuery.isLoading && projectsQuery.data?.length === 0 ? (
              <EmptyState
                title="No projects yet"
                description="Create a project first, then this console can show crawl, audit, content, Search Console, blog, and repository workflows."
              />
            ) : (
              children
            )}
          </main>
        </div>
      </div>
    </DashboardProjectContext.Provider>
  );
}

const navItems = [
  { label: 'Overview', href: '/dashboard', icon: LayoutDashboard },
  { label: 'Report', href: '/dashboard/report', icon: FileCheck2 },
  { label: 'Project Setup', href: '/dashboard/setup', icon: Rocket },
  { label: 'Audit Issues', href: '/dashboard/audit', icon: FileWarning },
  { label: 'Semantic Search', href: '/dashboard/semantic', icon: Database },
  { label: 'Weekly Planner', href: '/dashboard/planner', icon: Bot },
  { label: 'Search Console', href: '/dashboard/search-console', icon: Search },
  { label: 'Indexing', href: '/dashboard/indexing', icon: SearchCheck },
  { label: 'Rank Tracking', href: '/dashboard/rank-tracking', icon: LineChart },
  { label: 'Impact', href: '/dashboard/impact', icon: Activity },
  { label: 'SERP Snapshots', href: '/dashboard/serp-snapshots', icon: Camera },
  { label: 'Content', href: '/dashboard/content', icon: FileText },
  { label: 'GEO/AEO', href: '/dashboard/geo-aeo', icon: Target },
  { label: 'Blogs', href: '/dashboard/blogs', icon: Newspaper },
  { label: 'Repo Patches', href: '/dashboard/repos', icon: GitBranch },
];
