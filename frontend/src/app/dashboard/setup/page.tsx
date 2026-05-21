'use client';

import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileUp,
  GitBranch,
  Globe2,
  KeyRound,
  LibraryBig,
  Loader2,
  Play,
  Rocket,
  SearchCheck,
  Settings2,
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ActionNotice, EmptyState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { StatusBadge } from '@/components/dashboard/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { dashboardApi, latestCrawl, latestPlannerRun } from '@/lib/dashboard-api';
import type { CrawlJob, Project, UUID } from '@/types/dashboard';

type WorkflowStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

type WorkflowStep = {
  id: string;
  label: string;
  status: WorkflowStepStatus;
  detail?: string;
  href?: string;
};

const workflowTemplate: WorkflowStep[] = [
  { id: 'crawl', label: 'Crawl website', status: 'pending', href: '/dashboard/content' },
  { id: 'audit', label: 'Run SEO audit', status: 'pending', href: '/dashboard/content' },
  { id: 'semantic', label: 'Index semantic content', status: 'pending', href: '/dashboard/geo-aeo' },
  { id: 'internal_links', label: 'Generate internal link recommendations', status: 'pending', href: '/dashboard/planner' },
  { id: 'content', label: 'Generate content suggestions', status: 'pending', href: '/dashboard/content' },
  { id: 'geo_aeo', label: 'Score GEO/AEO readiness', status: 'pending', href: '/dashboard/geo-aeo' },
  { id: 'gsc', label: 'Sync Search Console if configured', status: 'pending', href: '/dashboard/search-console' },
  { id: 'repo', label: 'Scan repository if configured', status: 'pending', href: '/dashboard/repos' },
  { id: 'planner', label: 'Run weekly planner', status: 'pending', href: '/dashboard/planner' },
];

export default function ProjectSetupPage() {
  const queryClient = useQueryClient();
  const { projectId, project, projects, setProjectId, isLoading: projectLoading } = useDashboardProject();
  const [projectName, setProjectName] = useState(project?.name ?? '');
  const [websiteUrl, setWebsiteUrl] = useState(project?.domain ?? '');
  const [businessName, setBusinessName] = useState(project?.name ?? '');
  const [serviceArea, setServiceArea] = useState('');
  const [primaryServices, setPrimaryServices] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [blogFrequency, setBlogFrequency] = useState(3);
  const [localRepoPath, setLocalRepoPath] = useState('');
  const [gscPropertyUrl, setGscPropertyUrl] = useState('');
  const [gscPropertyType, setGscPropertyType] = useState<'domain' | 'url_prefix'>('url_prefix');
  const [businessSummary, setBusinessSummary] = useState('');
  const [brandVoice, setBrandVoice] = useState('');
  const [faqs, setFaqs] = useState('');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvDateStart, setCsvDateStart] = useState(defaultPastDate(28));
  const [csvDateEnd, setCsvDateEnd] = useState(defaultPastDate(1));
  const [notice, setNotice] = useState<string>();
  const [errorNotice, setErrorNotice] = useState<string>();
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>(workflowTemplate);
  const [currentStep, setCurrentStep] = useState<string>();
  const [workflowRunning, setWorkflowRunning] = useState(false);

  const crawlsQuery = useQuery({
    queryKey: ['crawls', projectId],
    queryFn: () => dashboardApi.crawls.list(projectId),
    enabled: Boolean(projectId),
    retry: false,
  });

  const latestCompletedCrawl = useMemo(
    () => crawlsQuery.data?.crawls.find((crawl) => crawl.status === 'completed'),
    [crawlsQuery.data?.crawls]
  );
  const latestAnyCrawl = latestCrawl(crawlsQuery.data?.crawls);

  const auditSummaryQuery = useQuery({
    queryKey: ['audit-summary', latestCompletedCrawl?.id],
    queryFn: () => dashboardApi.crawls.auditSummary(latestCompletedCrawl!.id),
    enabled: Boolean(latestCompletedCrawl?.id),
    retry: false,
  });

  const knowledgeQuery = useQuery({
    queryKey: ['knowledge-sources', projectId],
    queryFn: () => dashboardApi.knowledge.sources(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const propertiesQuery = useQuery({
    queryKey: ['gsc-properties', projectId],
    queryFn: () => dashboardApi.searchConsole.properties(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const gscSummaryQuery = useQuery({
    queryKey: ['gsc-summary', projectId],
    queryFn: () => dashboardApi.searchConsole.summary(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const repoConnectionsQuery = useQuery({
    queryKey: ['repo-connections', projectId],
    queryFn: () => dashboardApi.repos.connections(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  const plannerRunsQuery = useQuery({
    queryKey: ['planner-runs', projectId],
    queryFn: () => dashboardApi.planner.listRuns(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  });

  useEffect(() => {
    if (!project) return;
    setProjectName((current) => current || project.name);
    setBusinessName((current) => current || project.name);
    setWebsiteUrl((current) => current || project.domain || '');
  }, [project]);

  const createProjectMutation = useMutation({
    mutationFn: async () => {
      const created = await dashboardApi.createProject({
        name: projectName.trim(),
        domain: normalizeWebsiteUrl(websiteUrl),
        description: buildProjectDescription({
          businessName,
          serviceArea,
          primaryServices,
          targetAudience,
        }),
        keywords: splitList(primaryServices),
      });
      await dashboardApi.blogs.createPlan({
        project_id: created.id,
        title: `${created.name} weekly SEO blog plan`,
        target_site_url: created.domain ?? undefined,
        blogs_per_week: blogFrequency,
      });
      if (gscPropertyUrl.trim()) {
        await dashboardApi.searchConsole.registerManualProperty(created.id, {
          site_url: gscPropertyUrl,
          property_type: gscPropertyType,
          notes: 'Registered during project onboarding for CSV fallback.',
        });
      }
      return created;
    },
    onSuccess: async (created) => {
      setProjectId(created.id);
      setNotice('Project created and starter blog plan added.');
      await queryClient.invalidateQueries({ queryKey: ['dashboard-projects'] });
      await queryClient.invalidateQueries({ queryKey: ['blog-plans', created.id] });
      await queryClient.invalidateQueries({ queryKey: ['gsc-properties', created.id] });
      await queryClient.invalidateQueries({ queryKey: ['gsc-summary', created.id] });
    },
  });

  const knowledgeMutation = useMutation({
    mutationFn: async () => {
      const activeProjectId = requireProjectId(projectId);
      const source = await dashboardApi.knowledge.createSource({
        project_id: activeProjectId,
        source_type: 'business_profile',
        title: `${businessName || project?.name || 'Business'} profile`,
        description: 'Initial onboarding knowledge source',
        content: buildKnowledgeContent({
          businessName,
          websiteUrl: websiteForRun(project, websiteUrl),
          serviceArea,
          primaryServices,
          targetAudience,
          businessSummary,
          brandVoice,
          faqs,
        }),
        metadata: {
          onboarding: true,
          default_blog_frequency: blogFrequency,
          optional_gsc_property_url: gscPropertyUrl || undefined,
        },
      });
      try {
        await dashboardApi.knowledge.indexSource(source.id);
      } catch {
        return { source, indexed: false };
      }
      return { source, indexed: true };
    },
    onSuccess: async (result) => {
      setNotice(
        result.indexed
          ? 'Knowledge note saved and indexing started.'
          : 'Knowledge note saved. Indexing could not start, likely because Qdrant or embeddings are unavailable.'
      );
      await queryClient.invalidateQueries({ queryKey: ['knowledge-sources', projectId] });
    },
  });

  const repoMutation = useMutation({
    mutationFn: () =>
      dashboardApi.repos.createConnection({
        project_id: requireProjectId(projectId),
        provider: 'local',
        local_path: localRepoPath,
        framework: 'nextjs_app_router',
      }),
    onSuccess: async () => {
      setNotice('Local repository connection added.');
      setLocalRepoPath('');
      await queryClient.invalidateQueries({ queryKey: ['repo-connections', projectId] });
    },
  });

  const gscOAuthMutation = useMutation({
    mutationFn: () => dashboardApi.searchConsole.startOAuth(),
    onSuccess: (response) => {
      window.location.href = response.authorization_url;
    },
    onError: () => {
      setErrorNotice('Google OAuth is not configured on the backend. Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI to enable it.');
    },
  });

  const manualPropertyMutation = useMutation({
    mutationFn: () =>
      dashboardApi.searchConsole.registerManualProperty(requireProjectId(projectId), {
        site_url: gscPropertyUrl,
        property_type: gscPropertyType,
        notes: 'Registered manually for CSV fallback and onboarding context.',
      }),
    onSuccess: async (property) => {
      setNotice(`Manual GSC property saved: ${property.site_url}`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['gsc-properties', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['gsc-summary', projectId] }),
      ]);
    },
    onError: () => {
      setErrorNotice('Manual GSC property could not be saved. Check the URL and property type.');
    },
  });

  const csvMutation = useMutation({
    mutationFn: () => {
      if (!csvFile) throw new Error('Choose a CSV file first.');
      return dashboardApi.searchConsole.uploadCsv({
        file: csvFile,
        projectId,
        dateStart: csvDateStart,
        dateEnd: csvDateEnd,
        comparisonWindow: 'last_28_days',
      });
    },
    onSuccess: async (record) => {
      setNotice(`CSV fallback imported ${record.rows_imported} rows.`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['gsc-summary', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['gsc-imports', projectId] }),
      ]);
    },
    onError: () => {
      setErrorNotice('CSV upload failed. Check the file format and date range.');
    },
  });

  const checklist = [
    {
      title: 'Website URL added',
      done: Boolean(project?.domain || websiteUrl),
      detail: project?.domain || websiteUrl || 'Add a crawlable website URL.',
      icon: Globe2,
    },
    {
      title: 'First crawl completed',
      done: Boolean(latestCompletedCrawl),
      detail: latestCompletedCrawl
        ? `${latestCompletedCrawl.total_pages_crawled} pages crawled`
        : latestAnyCrawl
          ? `Latest crawl is ${latestAnyCrawl.status}`
          : 'Run the first full analysis.',
      icon: SearchCheck,
    },
    {
      title: 'SEO audit completed',
      done: auditSummaryQuery.data?.status === 'completed',
      detail: auditSummaryQuery.data
        ? `${auditSummaryQuery.data.total_issues} issues found`
        : 'Audit runs after a completed crawl.',
      icon: Settings2,
    },
    {
      title: 'Knowledge source added',
      done: Boolean(knowledgeQuery.data?.sources.length),
      detail: `${knowledgeQuery.data?.sources.length ?? 0} sources`,
      icon: LibraryBig,
    },
    {
      title: 'GSC or CSV configured',
      done: Boolean(
        propertiesQuery.data?.properties.some((property) => property.is_selected) ||
          (gscSummaryQuery.data?.imports_count ?? 0) > 0
      ),
      detail: propertiesQuery.data?.oauth_enabled
        ? 'OAuth available'
        : 'OAuth credentials missing; CSV fallback remains available.',
      icon: KeyRound,
    },
    {
      title: 'Repo connected',
      done: Boolean(repoConnectionsQuery.data?.connections.length),
      detail: `${repoConnectionsQuery.data?.connections.length ?? 0} repo connections`,
      icon: GitBranch,
    },
    {
      title: 'Weekly planner run completed',
      done: plannerRunsQuery.data?.runs.some((run) => run.status === 'completed') ?? false,
      detail: latestPlannerRun(plannerRunsQuery.data?.runs)?.status ?? 'No planner run yet',
      icon: Rocket,
    },
  ];

  const selectedGscProperty =
    gscSummaryQuery.data?.selected_property ||
    propertiesQuery.data?.properties.find((property) => property.is_selected);
  const gscStatus = selectedGscProperty
    ? selectedGscProperty.source_type === 'manual'
      ? 'Manual/CSV fallback'
      : 'OAuth connected'
    : 'Not configured';

  if (projectLoading) return <LoadingBlock label="Loading setup" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Project Setup
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Onboard a real project, add knowledge and repo context, then run the safe end-to-end workflow.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => void runFullAnalysis()}
          disabled={workflowRunning || !projectId || !websiteForRun(project, websiteUrl)}
        >
          {workflowRunning ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-2 h-4 w-4" />
          )}
          Run Full SEO Analysis
        </Button>
      </div>

      <ActionNotice message={notice} />
      <ActionNotice message={errorNotice} tone="error" />

      {!projects.length ? (
        <EmptyState
          title="Create your first project"
          description="Fill out the setup form below. Once the project exists, the workflow runner can crawl, analyze, and create review queues."
        />
      ) : null}

      <section className="grid gap-4 lg:grid-cols-7">
        <div className="space-y-4 lg:col-span-4">
          <SetupPanel title="Project basics" icon={Globe2}>
            <form className="space-y-4" onSubmit={handleCreateProject}>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Project name">
                  <Input
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    placeholder="HNX Technologies"
                  />
                </Field>
                <Field label="Website URL">
                  <Input
                    value={websiteUrl}
                    onChange={(event) => setWebsiteUrl(event.target.value)}
                    placeholder="https://example.com"
                  />
                </Field>
                <Field label="Business name">
                  <Input
                    value={businessName}
                    onChange={(event) => setBusinessName(event.target.value)}
                    placeholder="Business or brand name"
                  />
                </Field>
                <Field label="Target country/city/service area">
                  <Input
                    value={serviceArea}
                    onChange={(event) => setServiceArea(event.target.value)}
                    placeholder="United States, Dallas, remote"
                  />
                </Field>
                <Field label="Primary services">
                  <Input
                    value={primaryServices}
                    onChange={(event) => setPrimaryServices(event.target.value)}
                    placeholder="Web design, SEO, development"
                  />
                </Field>
                <Field label="Target audience">
                  <Input
                    value={targetAudience}
                    onChange={(event) => setTargetAudience(event.target.value)}
                    placeholder="B2B service businesses"
                  />
                </Field>
                <Field label="Default blog frequency">
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={blogFrequency}
                    onChange={(event) => setBlogFrequency(Number(event.target.value))}
                  />
                </Field>
                <Field label="Optional GSC property URL">
                  <Input
                    value={gscPropertyUrl}
                    onChange={(event) => setGscPropertyUrl(event.target.value)}
                    placeholder="sc-domain:example.com or https://example.com/"
                  />
                </Field>
                <Field label="GSC property type">
                  <select
                    className="h-10 w-full rounded-md border bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    value={gscPropertyType}
                    onChange={(event) =>
                      setGscPropertyType(event.target.value as 'domain' | 'url_prefix')
                    }
                  >
                    <option value="url_prefix">URL prefix</option>
                    <option value="domain">Domain</option>
                  </select>
                </Field>
              </div>
              <Button
                type="submit"
                disabled={createProjectMutation.isPending || !projectName.trim() || !websiteUrl.trim()}
              >
                Create project
              </Button>
            </form>
          </SetupPanel>

          <SetupPanel title="Knowledge onboarding" icon={LibraryBig}>
            <div className="space-y-4">
              <Field label="Business summary">
                <textarea
                  className="min-h-24 w-full rounded-md border bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  value={businessSummary}
                  onChange={(event) => setBusinessSummary(event.target.value)}
                  placeholder="What the business does, what makes it credible, and what customers should know."
                />
              </Field>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Brand voice">
                  <textarea
                    className="min-h-24 w-full rounded-md border bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    value={brandVoice}
                    onChange={(event) => setBrandVoice(event.target.value)}
                    placeholder="Direct, expert, friendly, local, technical..."
                  />
                </Field>
                <Field label="FAQs">
                  <textarea
                    className="min-h-24 w-full rounded-md border bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    value={faqs}
                    onChange={(event) => setFaqs(event.target.value)}
                    placeholder="Add common questions and answers."
                  />
                </Field>
              </div>
              <Button
                type="button"
                onClick={() => knowledgeMutation.mutate()}
                disabled={!projectId || knowledgeMutation.isPending || !businessSummary.trim()}
              >
                <Database className="mr-2 h-4 w-4" />
                Save and index knowledge
              </Button>
            </div>
          </SetupPanel>

          <SetupPanel title="Repo onboarding" icon={GitBranch}>
            <form className="space-y-3" onSubmit={handleRepoConnect}>
              <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                The local repo path must exist on the same machine or server running the backend.
              </p>
              <Input
                value={localRepoPath}
                onChange={(event) => setLocalRepoPath(event.target.value)}
                placeholder="C:\\path\\to\\nextjs-site"
              />
              <Button
                type="submit"
                disabled={!projectId || repoMutation.isPending || !localRepoPath.trim()}
              >
                Add repo connection
              </Button>
            </form>
          </SetupPanel>

          <SetupPanel title="Google Search Console" icon={KeyRound}>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <div className="rounded-md border bg-slate-50 p-3 text-sm">
                  <p className="font-medium text-slate-950">
                    {gscStatus}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {selectedGscProperty
                      ? `${selectedGscProperty.site_url} (${selectedGscProperty.property_type ?? 'url_prefix'})`
                      : propertiesQuery.data?.oauth_enabled
                        ? 'Connect Google Search Console and select a verified property, or register a manual CSV fallback property.'
                        : 'OAuth credentials are missing; register a manual property and use CSV fallback.'}
                  </p>
                </div>
                <div className="space-y-3 rounded-md border p-3">
                  <p className="text-sm font-medium text-slate-950">Manual property</p>
                  <Input
                    value={gscPropertyUrl}
                    onChange={(event) => setGscPropertyUrl(event.target.value)}
                    placeholder="sc-domain:example.com or https://example.com/"
                  />
                  <select
                    className="h-10 w-full rounded-md border bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    value={gscPropertyType}
                    onChange={(event) =>
                      setGscPropertyType(event.target.value as 'domain' | 'url_prefix')
                    }
                  >
                    <option value="url_prefix">URL prefix</option>
                    <option value="domain">Domain</option>
                  </select>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => manualPropertyMutation.mutate()}
                    disabled={!projectId || !gscPropertyUrl.trim() || manualPropertyMutation.isPending}
                  >
                    Save manual property
                  </Button>
                </div>
                <Button
                  type="button"
                  onClick={() => gscOAuthMutation.mutate()}
                  disabled={!propertiesQuery.data?.oauth_enabled || gscOAuthMutation.isPending}
                >
                  Connect Google Search Console
                </Button>
              </div>

              <form className="space-y-3" onSubmit={handleCsvUpload}>
                <p className="text-sm font-medium text-slate-950">CSV fallback</p>
                <Input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                />
                <div className="grid gap-3 md:grid-cols-2">
                  <Field label="Start date">
                    <Input
                      type="date"
                      value={csvDateStart}
                      onChange={(event) => setCsvDateStart(event.target.value)}
                    />
                  </Field>
                  <Field label="End date">
                    <Input
                      type="date"
                      value={csvDateEnd}
                      onChange={(event) => setCsvDateEnd(event.target.value)}
                    />
                  </Field>
                </div>
                <Button type="submit" variant="outline" disabled={!csvFile || csvMutation.isPending}>
                  <FileUp className="mr-2 h-4 w-4" />
                  Upload CSV
                </Button>
              </form>
            </div>
          </SetupPanel>
        </div>

        <div className="space-y-4 lg:col-span-3">
          <SetupPanel title="Setup checklist" icon={CheckCircle2}>
            <div className="grid gap-3">
              {checklist.map((item) => (
                <ChecklistCard key={item.title} {...item} />
              ))}
            </div>
          </SetupPanel>

          <WorkflowStatusPanel
            steps={workflowSteps}
            currentStep={currentStep}
            running={workflowRunning}
          />
        </div>
      </section>
    </div>
  );

  function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorNotice(undefined);
    createProjectMutation.mutate();
  }

  function handleRepoConnect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorNotice(undefined);
    repoMutation.mutate();
  }

  function handleCsvUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorNotice(undefined);
    csvMutation.mutate();
  }

  async function runFullAnalysis() {
    const activeProjectId = requireProjectId(projectId);
    const targetUrl = normalizeWebsiteUrl(websiteForRun(project, websiteUrl));
    setWorkflowRunning(true);
    setCurrentStep(undefined);
    setNotice(undefined);
    setErrorNotice(undefined);
    setWorkflowSteps(workflowTemplate.map((step) => ({ ...step, status: 'pending', detail: undefined })));

    let crawl: CrawlJob | undefined;

    try {
      crawl = await runWorkflowStep('crawl', async () => {
        const started = await dashboardApi.crawls.start({
          url: targetUrl,
          project_id: activeProjectId,
          name: 'First full SEO analysis crawl',
          max_pages: 50,
          depth: 2,
          priority: 'normal',
          render_javascript: true,
          respect_robots_txt: true,
        });
        const completed = await pollUntil(
          () => dashboardApi.crawls.status(started.id).then((response) => response.job),
          (item) => item.status,
          ['completed'],
          ['failed', 'cancelled'],
          120000
        );
        return {
          result: completed,
          detail: `${completed.total_pages_crawled} pages crawled`,
        };
      });

      await runWorkflowStep(
        'audit',
        async () => {
          const run = await dashboardApi.audits.start(crawl!.id);
          const completed = await pollUntil(
            () => dashboardApi.audits.status(run.id),
            (item) => item.status,
            ['completed'],
            ['failed'],
            120000
          );
          return { result: completed, detail: `${completed.total_issues} issues found` };
        },
        true
      );

      await runWorkflowStep(
        'semantic',
        async () => {
          const run = await dashboardApi.semantic.index(crawl!.id);
          const completed = await pollUntil(
            () => dashboardApi.semantic.status(run.id),
            (item) => item.status,
            ['completed'],
            ['failed'],
            120000
          );
          return { result: completed, detail: `${completed.indexed_vectors} vectors indexed` };
        },
        true
      );

      await runWorkflowStep(
        'internal_links',
        async () => {
          const result = await dashboardApi.internalLinks.generate(crawl!.id);
          return { result, detail: `${result.created_count} recommendations created` };
        },
        true
      );

      await runWorkflowStep(
        'content',
        async () => {
          const run = await dashboardApi.content.generate(crawl!.id);
          const completed = await pollUntil(
            () => dashboardApi.content.runStatus(run.id),
            (item) => item.status,
            ['completed'],
            ['failed'],
            120000
          );
          return { result: completed, detail: `${completed.total_suggestions} suggestions` };
        },
        true
      );

      await runWorkflowStep(
        'geo_aeo',
        async () => {
          const run = await dashboardApi.geoAeo.analyze(crawl!.id);
          const completed = await pollUntil(
            () => dashboardApi.geoAeo.runStatus(run.id),
            (item) => item.status,
            ['completed'],
            ['failed'],
            120000
          );
          return {
            result: completed,
            detail: `GEO ${Math.round(completed.average_geo_score)}, AEO ${Math.round(
              completed.average_aeo_score
            )}`,
          };
        },
        true
      );

      await runWorkflowStep(
        'gsc',
        async () => {
          const properties = await dashboardApi.searchConsole.properties(activeProjectId);
          const selected = properties.properties.find((item) => item.is_selected);
          if (!selected) {
            throw new SkippedStepError('No selected GSC property. CSV fallback can still be used.');
          }
          if (selected.source_type === 'manual') {
            throw new SkippedStepError('Manual GSC property saved. Automatic sync requires OAuth; use CSV fallback.');
          }
          if (!properties.oauth_enabled) {
            throw new SkippedStepError('OAuth credentials are missing. Use CSV fallback for Search Console data.');
          }
          const sync = await dashboardApi.searchConsole.sync(activeProjectId);
          if (sync.status === 'failed') {
            throw new SkippedStepError(sync.error_message || 'GSC sync could not run.');
          }
          return {
            result: sync,
            detail: `${sync.rows_fetched} rows, ${sync.opportunities_created} opportunities created`,
          };
        },
        true
      );

      await runWorkflowStep(
        'repo',
        async () => {
          const connections = await dashboardApi.repos.connections(activeProjectId);
          const connection = connections.connections[0];
          if (!connection) {
            throw new SkippedStepError('No repo connection configured.');
          }
          const scan = await dashboardApi.repos.scan(connection.id);
          await dashboardApi.repos.generatePatches(scan.id);
          return {
            result: scan,
            detail: `${scan.files_scanned} files scanned, ${scan.issues_found} issues`,
          };
        },
        true
      );

      await runWorkflowStep('planner', async () => {
        const run = await dashboardApi.planner.run(activeProjectId);
        return {
          result: run,
          detail: `${run.tasks_created} tasks created, ${run.high_priority_tasks} high priority`,
        };
      });

      setNotice('Full SEO analysis finished. Review approvals in the dashboard pages.');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Workflow failed.';
      setWorkflowSteps((steps) =>
        steps.map((step) =>
          step.status === 'pending'
            ? { ...step, status: 'skipped', detail: 'Skipped because the workflow stopped.' }
            : step
        )
      );
      setErrorNotice(message);
    } finally {
      setCurrentStep(undefined);
      setWorkflowRunning(false);
      await invalidateSetupData(activeProjectId, queryClient);
    }
  }

  async function runWorkflowStep<T>(
    stepId: string,
    action: () => Promise<{ result: T; detail?: string }>,
    continueOnFailure = false
  ): Promise<T | undefined> {
    setCurrentStep(stepId);
    updateWorkflowStep(stepId, { status: 'running', detail: 'Running...' });
    try {
      const { result, detail } = await action();
      updateWorkflowStep(stepId, { status: 'completed', detail });
      return result;
    } catch (error) {
      if (error instanceof SkippedStepError) {
        updateWorkflowStep(stepId, { status: 'skipped', detail: error.message });
        return undefined;
      }
      const detail = error instanceof Error ? error.message : 'Step failed.';
      updateWorkflowStep(stepId, { status: 'failed', detail });
      if (continueOnFailure) return undefined;
      throw error;
    }
  }

  function updateWorkflowStep(stepId: string, patch: Partial<WorkflowStep>) {
    setWorkflowSteps((steps) =>
      steps.map((step) => (step.id === stepId ? { ...step, ...patch } : step))
    );
  }
}

function SetupPanel({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-white">
      <div className="flex items-center gap-3 border-b px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-blue-50 text-blue-700">
          <Icon className="h-4 w-4" />
        </span>
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm font-medium text-slate-800">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function ChecklistCard({
  title,
  done,
  detail,
  icon: Icon,
}: {
  title: string;
  done: boolean;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex gap-3 rounded-md border bg-slate-50 p-3">
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${
          done ? 'bg-emerald-50 text-emerald-700' : 'bg-white text-slate-500'
        }`}
      >
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-slate-950">{title}</p>
          {done ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : null}
        </div>
        <p className="mt-1 break-words text-sm text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}

function WorkflowStatusPanel({
  steps,
  currentStep,
  running,
}: {
  steps: WorkflowStep[];
  currentStep?: string;
  running: boolean;
}) {
  const completed = steps.filter((step) => step.status === 'completed').length;
  const failed = steps.filter((step) => step.status === 'failed').length;
  const skipped = steps.filter((step) => step.status === 'skipped').length;
  const active = steps.find((step) => step.id === currentStep);

  return (
    <section className="rounded-lg border bg-white">
      <div className="flex items-center gap-3 border-b px-5 py-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-emerald-50 text-emerald-700">
          <Rocket className="h-4 w-4" />
        </span>
        <div>
          <h3 className="text-base font-semibold text-slate-950">End-to-end status</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {running
              ? `Current step: ${active?.label ?? 'Starting'}`
              : 'Safe workflow runner is idle.'}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 border-b p-5 text-center text-sm">
        <StatusCount label="Completed" value={completed} />
        <StatusCount label="Failed" value={failed} />
        <StatusCount label="Skipped" value={skipped} />
      </div>
      <div className="divide-y">
        {steps.map((step) => (
          <div key={step.id} className="flex items-start justify-between gap-3 px-5 py-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-950">{step.label}</p>
              {step.detail ? (
                <p className="mt-1 break-words text-sm text-muted-foreground">{step.detail}</p>
              ) : null}
              {step.href ? (
                <a className="mt-2 inline-block text-xs font-medium text-blue-700" href={step.href}>
                  View results
                </a>
              ) : null}
            </div>
            <StatusBadge status={step.status} />
          </div>
        ))}
      </div>
      <div className="flex gap-2 border-t bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          This workflow never applies repo patches, creates PRs, publishes drafts, merges, or deploys.
          It only creates reviewable outputs.
        </p>
      </div>
    </section>
  );
}

function StatusCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-slate-50 p-3">
      <p className="text-2xl font-semibold text-slate-950">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

class SkippedStepError extends Error {}

function requireProjectId(projectId?: UUID): UUID {
  if (!projectId) throw new Error('Select or create a project first.');
  return projectId;
}

function websiteForRun(project?: Project, websiteUrl?: string) {
  return websiteUrl || project?.domain || '';
}

function normalizeWebsiteUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function splitList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildProjectDescription(input: {
  businessName: string;
  serviceArea: string;
  primaryServices: string;
  targetAudience: string;
}) {
  return [
    input.businessName ? `Business: ${input.businessName}` : '',
    input.serviceArea ? `Service area: ${input.serviceArea}` : '',
    input.primaryServices ? `Services: ${input.primaryServices}` : '',
    input.targetAudience ? `Audience: ${input.targetAudience}` : '',
  ]
    .filter(Boolean)
    .join('\n');
}

function buildKnowledgeContent(input: {
  businessName: string;
  websiteUrl: string;
  serviceArea: string;
  primaryServices: string;
  targetAudience: string;
  businessSummary: string;
  brandVoice: string;
  faqs: string;
}) {
  return [
    `Business name: ${input.businessName || 'Not provided'}`,
    `Website: ${input.websiteUrl || 'Not provided'}`,
    `Service area: ${input.serviceArea || 'Not provided'}`,
    `Primary services: ${input.primaryServices || 'Not provided'}`,
    `Target audience: ${input.targetAudience || 'Not provided'}`,
    '',
    'Business summary:',
    input.businessSummary || 'Not provided',
    '',
    'Brand voice:',
    input.brandVoice || 'Not provided',
    '',
    'FAQs:',
    input.faqs || 'Not provided',
  ].join('\n');
}

async function pollUntil<T>(
  load: () => Promise<T>,
  statusOf: (_item: T) => string,
  doneStatuses: string[],
  failedStatuses: string[],
  timeoutMs: number
) {
  const deadline = Date.now() + timeoutMs;
  let lastItem: T | undefined;
  while (Date.now() < deadline) {
    lastItem = await load();
    const status = statusOf(lastItem);
    if (doneStatuses.includes(status)) return lastItem;
    if (failedStatuses.includes(status)) {
      throw new Error(`Step ended with status ${status}.`);
    }
    await delay(3000);
  }
  const lastStatus = lastItem ? statusOf(lastItem) : 'unknown';
  throw new Error(`Timed out waiting for completion. Last status: ${lastStatus}.`);
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function defaultPastDate(daysAgo: number) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString().slice(0, 10);
}

async function invalidateSetupData(projectId: UUID, queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['crawls', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['knowledge-sources', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-properties', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['gsc-summary', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['repo-connections', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-runs', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['planner-summary', projectId] }),
  ]);
}
