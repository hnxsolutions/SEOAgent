'use client';

// The per-page icons now live with the navigation itself, in lib/dashboard-nav.
import { LogOut, Plus, RefreshCw, Rocket } from 'lucide-react';
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
import { isActiveHref, navSections, sectionForPath } from '@/lib/dashboard-nav';
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
  // Which area of the product this page belongs to. Drives both the highlighted
  // sidebar entry and the row of sibling tabs under the header.
  const activeSection = sectionForPath(pathname);
  // The setup page must render its own create form even when the account has
  // zero projects — otherwise a new user hits a dead-end empty state and can
  // never create a first project.
  const allowsEmptyProject = pathname === '/dashboard/setup';
  const [projectId, setProjectIdState] = useState<UUID | undefined>();
  const [authChecked, setAuthChecked] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    const token = window.localStorage.getItem('access_token');
    if (!token) {
      window.location.replace('/login');
      return;
    }
    setHasToken(true);
    setAuthChecked(true);
  }, []);

  const projectsQuery = useQuery({
    queryKey: ['dashboard-projects'],
    queryFn: dashboardApi.listProjects,
    enabled: hasToken,
    retry: false,
  });

  useEffect(() => {
    const data = projectsQuery.data;
    if (!data) return;
    const stored = window.localStorage.getItem('dashboard_project_id');
    if (data.length === 0) {
      // No projects: drop any stale stored id and clear the selection.
      if (stored) window.localStorage.removeItem('dashboard_project_id');
      setProjectIdState(undefined);
      return;
    }
    const storedIsValid = Boolean(stored && data.some((project) => project.id === stored));
    if (stored && !storedIsValid) {
      // Stored id points at a deleted/missing project — remove it.
      window.localStorage.removeItem('dashboard_project_id');
    }
    setProjectIdState((current) => {
      if (current && data.some((project) => project.id === current)) return current;
      const next = (storedIsValid ? stored : data[0]?.id) as UUID | undefined;
      if (next) window.localStorage.setItem('dashboard_project_id', next);
      return next;
    });
  }, [projectsQuery.data]);

  const setProjectId = (nextProjectId: UUID) => {
    window.localStorage.setItem('dashboard_project_id', nextProjectId);
    setProjectIdState(nextProjectId);
  };

  const logout = () => {
    window.localStorage.removeItem('access_token');
    window.localStorage.removeItem('refresh_token');
    window.localStorage.removeItem('auth-storage');
    window.location.replace('/login');
  };

  const project = useMemo(
    () => projectsQuery.data?.find((item) => item.id === projectId),
    [projectsQuery.data, projectId]
  );

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="rounded-lg border bg-white px-5 py-4 text-sm text-muted-foreground">
          Redirecting to login
        </div>
      </div>
    );
  }

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
            {navSections.map((section) => {
              const active = section === activeSection;
              return (
                <Link
                  key={section.label}
                  href={section.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950',
                    active && 'bg-blue-50 font-semibold text-blue-700'
                  )}
                >
                  <section.icon className="h-4 w-4" aria-hidden="true" />
                  <span className="flex-1">{section.label}</span>
                  {section.children ? (
                    <span className="text-xs tabular-nums text-slate-400">
                      {section.children.length}
                    </span>
                  ) : null}
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
                  {navSections.map((section) => (
                    <Link
                      key={section.label}
                      href={section.href}
                      className={cn(
                        'flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100',
                        section === activeSection && 'bg-blue-50 text-blue-700'
                      )}
                      title={section.label}
                    >
                      <section.icon className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  ))}
                </div>
                <ProjectSelector
                  projectId={projectId}
                  projects={projectsQuery.data ?? []}
                  isLoading={projectsQuery.isLoading}
                  isFetching={projectsQuery.isFetching}
                  isError={projectsQuery.isError}
                  onChange={setProjectId}
                  onRefresh={() => void projectsQuery.refetch()}
                  onLoginAgain={logout}
                />
                <Link
                  href="/dashboard/setup"
                  className="inline-flex h-10 items-center justify-center rounded-md border bg-white px-3 text-sm font-medium shadow-sm transition-colors hover:bg-slate-50"
                >
                  <Rocket className="mr-2 h-4 w-4" aria-hidden="true" />
                  Setup
                </Link>
                <button
                  type="button"
                  onClick={logout}
                  className="inline-flex h-10 items-center justify-center rounded-md border bg-white px-3 text-sm font-medium shadow-sm transition-colors hover:bg-slate-50"
                >
                  <LogOut className="mr-2 h-4 w-4" aria-hidden="true" />
                  Logout
                </button>
              </div>
            </div>
            {activeSection?.children ? (
              <div className="border-t bg-white/95 px-4 sm:px-6 lg:px-8">
                <nav
                  aria-label={`${activeSection.label} pages`}
                  className="-mb-px flex gap-1 overflow-x-auto"
                >
                  {activeSection.children.map((child) => {
                    const active = isActiveHref(pathname, child.href);
                    return (
                      <Link
                        key={child.href}
                        href={child.href}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                          active
                            ? 'border-blue-600 text-blue-700'
                            : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-900'
                        )}
                      >
                        <child.icon className="h-4 w-4" aria-hidden="true" />
                        {child.label}
                      </Link>
                    );
                  })}
                </nav>
              </div>
            ) : null}
          </header>

          <main className="px-4 py-6 sm:px-6 lg:px-8">
            {projectsQuery.isError ? (
              <ErrorState
                title="Projects could not load"
                message="Check that the backend is running and that your session token is valid."
                onRetry={() => void projectsQuery.refetch()}
              />
            ) : !projectsQuery.isLoading &&
              projectsQuery.data?.length === 0 &&
              !allowsEmptyProject ? (
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

function ProjectSelector({
  projectId,
  projects,
  isLoading,
  isFetching,
  isError,
  onChange,
  onRefresh,
  onLoginAgain,
}: {
  projectId?: UUID;
  projects: Project[];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  onChange: (_projectId: UUID) => void;
  onRefresh: () => void;
  onLoginAgain: () => void;
}) {
  const selectBase =
    'h-10 min-w-56 rounded-md border bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring';
  const disabledSelect = cn(selectBase, 'cursor-not-allowed text-muted-foreground opacity-70');
  const iconButton =
    'inline-flex h-10 w-10 items-center justify-center rounded-md border bg-white text-slate-600 shadow-sm transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50';

  if (isError) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <select disabled aria-label="Select project" className={disabledSelect}>
            <option>Projects unavailable</option>
          </select>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isFetching}
            className="inline-flex h-10 items-center justify-center rounded-md border bg-white px-3 text-sm font-medium shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw
              className={cn('mr-2 h-4 w-4', isFetching && 'animate-spin')}
              aria-hidden="true"
            />
            Retry
          </button>
          <button
            type="button"
            onClick={onLoginAgain}
            className="inline-flex h-10 items-center justify-center rounded-md border bg-white px-3 text-sm font-medium shadow-sm transition-colors hover:bg-slate-50"
          >
            <LogOut className="mr-2 h-4 w-4" aria-hidden="true" />
            Login again
          </button>
        </div>
        <p className="text-xs text-red-600">
          Projects could not load. Check backend or login again.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        <select disabled aria-label="Select project" className={disabledSelect}>
          <option>Loading projects…</option>
        </select>
        <p className="text-xs text-muted-foreground">Fetching your project workspace.</p>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <select disabled aria-label="Select project" className={disabledSelect}>
            <option>No projects yet</option>
          </select>
          <Link
            href="/dashboard/setup"
            className="inline-flex h-10 items-center justify-center rounded-md bg-blue-600 px-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
            Create Project
          </Link>
        </div>
        <p className="text-xs text-muted-foreground">Create your first project to begin.</p>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <select
        className={selectBase}
        value={projectId ?? ''}
        onChange={(event) => onChange(event.target.value as UUID)}
        aria-label="Select project"
      >
        {!projectId ? <option value="">Select project</option> : null}
        {projects.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onRefresh}
        disabled={isFetching}
        aria-label="Refresh projects"
        title="Refresh projects"
        className={iconButton}
      >
        <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} aria-hidden="true" />
      </button>
    </div>
  );
}

