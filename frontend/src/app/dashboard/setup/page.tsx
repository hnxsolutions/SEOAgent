'use client';

import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  Building2,
  CheckCircle2,
  Globe2,
  Goal,
  ListChecks,
  MapPin,
  Pencil,
  Plus,
  Save,
  SearchCheck,
  UsersRound,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ActionNotice, EmptyState, LoadingBlock } from '@/components/dashboard/DashboardStates';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useDashboardProject } from '@/components/dashboard/DashboardShell';
import { extractApiError } from '@/lib/api';
import { dashboardApi, type ProjectContextPayload } from '@/lib/dashboard-api';
import type { Project } from '@/types/dashboard';

type OnboardingMode = 'create' | 'edit';

type ProjectContextForm = {
  projectName: string;
  websiteUrl: string;
  businessName: string;
  industry: string;
  targetLocation: string;
  targetAudience: string;
  primaryServices: string;
  targetKeywords: string;
  competitorUrls: string;
  seoGoal: string;
  brandTone: string;
};

type OnboardingStep = {
  title: string;
  subtitle: string;
  icon: LucideIcon;
};

const onboardingSteps: OnboardingStep[] = [
  { title: 'Website', subtitle: 'URL and project name', icon: Globe2 },
  { title: 'Business', subtitle: 'Name and industry', icon: Building2 },
  { title: 'Audience', subtitle: 'Location and buyers', icon: UsersRound },
  { title: 'Services', subtitle: 'What you sell', icon: Briefcase },
  { title: 'Keywords', subtitle: 'Priority topics', icon: SearchCheck },
  { title: 'Competitors', subtitle: 'Manual context only', icon: ListChecks },
  { title: 'Goal', subtitle: 'Outcome and tone', icon: Goal },
];

const emptyForm: ProjectContextForm = {
  projectName: '',
  websiteUrl: '',
  businessName: '',
  industry: '',
  targetLocation: '',
  targetAudience: '',
  primaryServices: '',
  targetKeywords: '',
  competitorUrls: '',
  seoGoal: '',
  brandTone: '',
};

export default function ProjectSetupPage() {
  const queryClient = useQueryClient();
  const { projectId, project, projects, setProjectId, isLoading: projectLoading } = useDashboardProject();
  const [mode, setMode] = useState<OnboardingMode>('edit');
  const [activeStep, setActiveStep] = useState(0);
  const [form, setForm] = useState<ProjectContextForm>(emptyForm);
  const [notice, setNotice] = useState<string>();
  const [errorNotice, setErrorNotice] = useState<string>();
  const selectedProjectForm = useMemo(() => projectToForm(project), [project]);

  useEffect(() => {
    if (!projects.length) {
      setMode('create');
      setForm(emptyForm);
    }
  }, [projects.length]);

  useEffect(() => {
    if (mode === 'edit') {
      setForm(selectedProjectForm);
    }
  }, [mode, selectedProjectForm]);

  const stepErrors = useMemo(() => validateStep(activeStep, form), [activeStep, form]);
  const allErrors = useMemo(() => validateForm(form), [form]);
  const completedSteps = onboardingSteps.filter((_, index) => isStepComplete(index, form)).length;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = buildPayload(form);
      if (mode === 'edit' && projectId) {
        return dashboardApi.updateProject(projectId, payload);
      }
      return dashboardApi.createProject(payload);
    },
    onSuccess: async (savedProject) => {
      setNotice(mode === 'edit' ? 'Project context updated.' : 'Project created with onboarding context.');
      setErrorNotice(undefined);
      setMode('edit');
      setProjectId(savedProject.id);
      setForm(projectToForm(savedProject));
      queryClient.setQueryData<Project[]>(['dashboard-projects'], (current) => upsertProject(current, savedProject));
      await queryClient.invalidateQueries({ queryKey: ['dashboard-projects'] });
    },
    onError: (error) => {
      setErrorNotice(extractApiError(error, 'Project context could not be saved.'));
    },
  });

  if (projectLoading) return <LoadingBlock label="Loading project setup" />;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
            Project Onboarding
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Add client context so SEO runs, content suggestions, planner tasks, and reports stay project-specific.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={mode === 'edit' ? 'default' : 'outline'}
            onClick={() => {
              setMode('edit');
              setForm(selectedProjectForm);
            }}
            disabled={!projectId}
          >
            <Pencil className="mr-2 h-4 w-4" aria-hidden="true" />
            Edit Project Context
          </Button>
          <Button
            type="button"
            variant={mode === 'create' ? 'default' : 'outline'}
            onClick={() => {
              setMode('create');
              setForm(emptyForm);
              setActiveStep(0);
            }}
          >
            <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
            New Project
          </Button>
        </div>
      </div>

      <ActionNotice message={notice} />
      <ActionNotice message={errorNotice} tone="error" />

      {!projects.length ? (
        <EmptyState
          title="Create your first project"
          description="The context fields are optional for old projects, but filling them in makes reports more client-ready."
        />
      ) : null}

      <section className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-lg border bg-white">
          <div className="border-b px-5 py-4">
            <p className="text-sm font-semibold text-slate-950">
              {mode === 'edit' ? 'Edit selected project' : 'Create project'}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {completedSteps} of {onboardingSteps.length} steps ready
            </p>
          </div>
          <div className="space-y-1 p-2">
            {onboardingSteps.map((step, index) => {
              const Icon = step.icon;
              const selected = activeStep === index;
              const done = isStepComplete(index, form);
              return (
                <button
                  key={step.title}
                  type="button"
                  onClick={() => setActiveStep(index)}
                  className={`flex min-h-14 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition-colors ${
                    selected
                      ? 'bg-blue-50 text-blue-800'
                      : 'text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-white">
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{step.title}</span>
                    <span className="block text-xs text-muted-foreground">{step.subtitle}</span>
                  </span>
                  {done ? <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
        </div>

        <form className="rounded-lg border bg-white" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-medium text-muted-foreground">Step {activeStep + 1}</p>
              <h3 className="mt-1 text-lg font-semibold text-slate-950">
                {onboardingSteps[activeStep].title}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">{onboardingSteps[activeStep].subtitle}</p>
            </div>
            <span className="inline-flex h-8 items-center rounded-md border bg-slate-50 px-3 text-xs font-medium text-slate-700">
              {mode === 'edit' ? project?.name ?? 'Selected project' : 'New project'}
            </span>
          </div>

          <div className="min-h-[360px] p-5">
            <StepFields activeStep={activeStep} form={form} setForm={setForm} />
            {stepErrors.length ? (
              <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                {stepErrors.map((error) => (
                  <p key={error}>{error}</p>
                ))}
              </div>
            ) : null}
          </div>

          <div className="flex flex-col gap-3 border-t bg-slate-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <Button
              type="button"
              variant="outline"
              onClick={() => setActiveStep((step) => Math.max(0, step - 1))}
              disabled={activeStep === 0}
            >
              <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
              Back
            </Button>
            <div className="flex flex-wrap items-center gap-2">
              {allErrors.length ? (
                <span className="text-sm text-amber-700">{allErrors[0]}</span>
              ) : null}
              {activeStep < onboardingSteps.length - 1 ? (
                <Button type="button" onClick={() => setActiveStep((step) => Math.min(onboardingSteps.length - 1, step + 1))}>
                  Next
                  <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />
                </Button>
              ) : (
                <Button type="submit" disabled={saveMutation.isPending || allErrors.length > 0}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {saveMutation.isPending ? 'Saving' : mode === 'edit' ? 'Save Context' : 'Create Project'}
                </Button>
              )}
            </div>
          </div>
        </form>
      </section>

      <ContextSummary project={project} />
    </div>
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(undefined);
    setErrorNotice(undefined);
    if (allErrors.length) {
      setErrorNotice(allErrors.join(' '));
      return;
    }
    saveMutation.mutate();
  }
}

function StepFields({
  activeStep,
  form,
  setForm,
}: {
  activeStep: number;
  form: ProjectContextForm;
  setForm: (_form: ProjectContextForm) => void;
}) {
  const update = (field: keyof ProjectContextForm, value: string) =>
    setForm({ ...form, [field]: value });

  if (activeStep === 0) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          id="project-name"
          label="Project name"
          value={form.projectName}
          onChange={(value) => update('projectName', value)}
          placeholder="Acme Studio SEO"
          example="Example: Phoenix Remodeling SEO"
        />
        <TextField
          id="website-url"
          label="Website URL"
          value={form.websiteUrl}
          onChange={(value) => update('websiteUrl', value)}
          placeholder="https://example.com"
          example="Use the client site, not a competitor URL."
        />
      </div>
    );
  }

  if (activeStep === 1) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          id="business-name"
          label="Business name"
          value={form.businessName}
          onChange={(value) => update('businessName', value)}
          placeholder="Acme Studio"
          example="Use the public client or brand name."
        />
        <TextField
          id="industry"
          label="Industry"
          value={form.industry}
          onChange={(value) => update('industry', value)}
          placeholder="Home services"
          example="Examples: SaaS, healthcare, legal, ecommerce."
        />
      </div>
    );
  }

  if (activeStep === 2) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          id="target-location"
          label="Target location"
          value={form.targetLocation}
          onChange={(value) => update('targetLocation', value)}
          placeholder="Phoenix, AZ"
          example="Use city, region, country, or remote market."
        />
        <TextAreaField
          id="target-audience"
          label="Target audience"
          value={form.targetAudience}
          onChange={(value) => update('targetAudience', value)}
          placeholder="Homeowners comparing kitchen remodeling companies"
          example="Mention buyer role, problem, and decision stage."
        />
      </div>
    );
  }

  if (activeStep === 3) {
    return (
      <TextAreaField
        id="primary-services"
        label="Primary services"
        value={form.primaryServices}
        onChange={(value) => update('primaryServices', value)}
        placeholder={'Kitchen remodeling\nBathroom remodeling\nCustom cabinets'}
        example="Add one service per line, or separate values with commas."
        rows={9}
      />
    );
  }

  if (activeStep === 4) {
    return (
      <TextAreaField
        id="target-keywords"
        label="Target keywords"
        value={form.targetKeywords}
        onChange={(value) => update('targetKeywords', value)}
        placeholder={'kitchen remodeling Phoenix\ncustom cabinets Phoenix\nbathroom renovation contractor'}
        example="These are manual targets. Rankings are only shown when real GSC or manual SERP data exists."
        rows={9}
      />
    );
  }

  if (activeStep === 5) {
    return (
      <TextAreaField
        id="competitor-urls"
        label="Optional competitor URLs"
        value={form.competitorUrls}
        onChange={(value) => update('competitorUrls', value)}
        placeholder={'https://competitor-one.example\nhttps://competitor-two.example'}
        example="Manual context only. The MVP will not crawl competitors or claim competitor analysis."
        rows={9}
      />
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <TextAreaField
        id="seo-goal"
        label="SEO goal"
        value={form.seoGoal}
        onChange={(value) => update('seoGoal', value)}
        placeholder="Increase qualified consultation requests from local service pages."
        example="Keep this outcome-oriented and client-readable."
      />
      <TextField
        id="brand-tone"
        label="Brand tone"
        value={form.brandTone}
        onChange={(value) => update('brandTone', value)}
        placeholder="Warm, expert, direct"
        example="Examples: clinical, friendly, premium, practical."
      />
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  example,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (_value: string) => void;
  placeholder: string;
  example: string;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="mt-2"
      />
      <p className="mt-2 text-xs text-muted-foreground">{example}</p>
    </div>
  );
}

function TextAreaField({
  id,
  label,
  value,
  onChange,
  placeholder,
  example,
  rows = 6,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (_value: string) => void;
  placeholder: string;
  example: string;
  rows?: number;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <textarea
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="mt-2 w-full resize-y rounded-md border bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      <p className="mt-2 text-xs text-muted-foreground">{example}</p>
    </div>
  );
}

function ContextSummary({ project }: { project?: Project }) {
  const rows = projectContextRows(project);
  return (
    <section className="rounded-lg border bg-white">
      <div className="flex flex-col gap-2 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Current Project Context</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Missing fields remain visible as Not provided in dashboards and reports.
          </p>
        </div>
        <span className="inline-flex h-8 items-center rounded-md border bg-slate-50 px-3 text-xs font-medium text-slate-700">
          {project?.name ?? 'No project selected'}
        </span>
      </div>
      <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-4">
        {rows.map((row) => (
          <div key={row.label} className="rounded-md border bg-slate-50 px-3 py-3">
            <div className="flex items-center gap-2">
              <row.icon className="h-4 w-4 text-slate-500" aria-hidden="true" />
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{row.label}</p>
            </div>
            <p className="mt-2 break-words text-sm font-medium text-slate-900">{row.value}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function projectToForm(project?: Project): ProjectContextForm {
  if (!project) return emptyForm;
  return {
    projectName: project.name ?? '',
    websiteUrl: project.domain ?? '',
    businessName: project.business_name ?? '',
    industry: project.industry ?? '',
    targetLocation: project.target_location ?? '',
    targetAudience: project.target_audience ?? '',
    primaryServices: (project.primary_services ?? []).join('\n'),
    targetKeywords: (project.target_keywords ?? project.keywords ?? []).join('\n'),
    competitorUrls: (project.competitor_urls ?? []).join('\n'),
    seoGoal: project.seo_goal ?? '',
    brandTone: project.brand_tone ?? '',
  };
}

function buildPayload(form: ProjectContextForm): ProjectContextPayload {
  const targetKeywords = splitList(form.targetKeywords);
  const primaryServices = splitList(form.primaryServices);
  const competitorUrls = splitList(form.competitorUrls).map(normalizeWebsiteUrl);
  return {
    name: form.projectName.trim(),
    domain: normalizeWebsiteUrl(form.websiteUrl),
    description: buildDescription(form),
    keywords: targetKeywords.length ? targetKeywords : null,
    business_name: nullableText(form.businessName),
    industry: nullableText(form.industry),
    target_location: nullableText(form.targetLocation),
    target_audience: nullableText(form.targetAudience),
    primary_services: primaryServices.length ? primaryServices : null,
    target_keywords: targetKeywords.length ? targetKeywords : null,
    competitor_urls: competitorUrls.length ? competitorUrls : null,
    seo_goal: nullableText(form.seoGoal),
    brand_tone: nullableText(form.brandTone),
  };
}

function validateStep(step: number, form: ProjectContextForm) {
  if (step === 0) {
    const errors = [];
    if (!form.projectName.trim()) errors.push('Project name is required.');
    if (!form.websiteUrl.trim()) {
      errors.push('Website URL is required.');
    } else if (!isWebsiteLike(form.websiteUrl)) {
      errors.push('Use a valid website URL or domain.');
    }
    return errors;
  }
  if (step === 5) {
    const invalidUrls = splitList(form.competitorUrls).filter((url) => !isWebsiteLike(url));
    return invalidUrls.length ? [`Check competitor URL format: ${invalidUrls[0]}`] : [];
  }
  return [];
}

function validateForm(form: ProjectContextForm) {
  return [...validateStep(0, form), ...validateStep(5, form)];
}

function isStepComplete(step: number, form: ProjectContextForm) {
  if (validateStep(step, form).length > 0) return false;
  if (step === 0) return Boolean(form.projectName.trim() && form.websiteUrl.trim());
  if (step === 1) return Boolean(form.businessName.trim() && form.industry.trim());
  if (step === 2) return Boolean(form.targetLocation.trim() && form.targetAudience.trim());
  if (step === 3) return splitList(form.primaryServices).length > 0;
  if (step === 4) return splitList(form.targetKeywords).length > 0;
  if (step === 5) return true;
  return Boolean(form.seoGoal.trim() && form.brandTone.trim());
}

function splitList(value: string) {
  return value
    .replace(/\r/g, '')
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeWebsiteUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^(localhost|127\.|0\.0\.0\.0|\[::1\])/i.test(trimmed)) return `http://${trimmed}`;
  return `https://${trimmed}`;
}

function isWebsiteLike(value: string) {
  const normalized = normalizeWebsiteUrl(value);
  try {
    const parsed = new URL(normalized);
    return Boolean(parsed.hostname) && ['http:', 'https:'].includes(parsed.protocol);
  } catch {
    return false;
  }
}

function nullableText(value: string) {
  const trimmed = value.trim();
  return trimmed || null;
}

function buildDescription(form: ProjectContextForm) {
  return [
    nullableText(form.businessName) ? `Business: ${form.businessName.trim()}` : '',
    nullableText(form.industry) ? `Industry: ${form.industry.trim()}` : '',
    nullableText(form.targetLocation) ? `Target location: ${form.targetLocation.trim()}` : '',
    nullableText(form.targetAudience) ? `Audience: ${form.targetAudience.trim()}` : '',
    splitList(form.primaryServices).length ? `Services: ${splitList(form.primaryServices).join(', ')}` : '',
    nullableText(form.seoGoal) ? `SEO goal: ${form.seoGoal.trim()}` : '',
  ]
    .filter(Boolean)
    .join('\n');
}

function projectContextRows(project?: Project): Array<{ label: string; value: string; icon: LucideIcon }> {
  return [
    { label: 'Business', value: displayText(project?.business_name), icon: Building2 },
    { label: 'Industry', value: displayText(project?.industry), icon: Briefcase },
    { label: 'Location', value: displayText(project?.target_location), icon: MapPin },
    { label: 'Audience', value: displayText(project?.target_audience), icon: UsersRound },
    { label: 'Services', value: displayList(project?.primary_services), icon: ListChecks },
    { label: 'Keywords', value: displayList(project?.target_keywords ?? project?.keywords), icon: SearchCheck },
    { label: 'SEO Goal', value: displayText(project?.seo_goal), icon: Goal },
    { label: 'Brand Tone', value: displayText(project?.brand_tone), icon: Pencil },
  ];
}

function displayText(value?: string | null) {
  return value?.trim() || 'Not provided';
}

function displayList(value?: string[] | null) {
  return value?.length ? value.join(', ') : 'Not provided';
}

function upsertProject(current: Project[] | undefined, project: Project) {
  const projects = current ?? [];
  const index = projects.findIndex((item) => item.id === project.id);
  if (index === -1) return [project, ...projects];
  return projects.map((item) => (item.id === project.id ? project : item));
}
