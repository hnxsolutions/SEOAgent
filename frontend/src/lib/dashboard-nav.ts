/**
 * The dashboard's navigation, as sections rather than a list.
 *
 * There were twenty-eight links in a flat sidebar. Past about the twelfth the
 * list ran off the bottom of the screen, which is how "Search Console" — a page
 * that exists and works — came to be reported as missing: it was twentieth.
 * A list that long also stops being navigation, because nothing in it tells you
 * where you are or what belongs with what.
 *
 * So the sidebar now carries one entry per area of work, and the pages inside an
 * area appear as horizontal tabs once you are in it. Every page is still one or
 * two clicks away, and the sidebar fits on a laptop screen without scrolling.
 *
 * Ordering within a section follows the order you would actually use the pages,
 * not alphabetical: the first child is what opens when the section is clicked,
 * so it should be the one most people want.
 */
import {
  Activity,
  BadgeCheck,
  Bot,
  Camera,
  Cpu,
  Database,
  FileCheck2,
  FileText,
  FileWarning,
  GitBranch,
  GitPullRequest,
  Gauge,
  KeyRound,
  LayoutDashboard,
  LineChart,
  Newspaper,
  Rocket,
  Search,
  SearchCheck,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type NavChild = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export type NavSection = {
  label: string;
  /** Shown in the sidebar and, when the section has children, as the tab group heading. */
  icon: LucideIcon;
  /** Where the sidebar entry goes. For a section with children this is the first child. */
  href: string;
  children?: NavChild[];
};

export const navSections: NavSection[] = [
  {
    label: 'Overview',
    icon: LayoutDashboard,
    href: '/dashboard',
  },
  {
    label: 'Mission Control',
    icon: Gauge,
    href: '/dashboard/mission-control',
  },
  {
    label: 'Search',
    icon: Search,
    href: '/dashboard/search-console',
    children: [
      { label: 'Search Console', href: '/dashboard/search-console', icon: Search },
      { label: 'Keywords', href: '/dashboard/keywords', icon: KeyRound },
      { label: 'Rank Tracking', href: '/dashboard/rank-tracking', icon: LineChart },
      { label: 'Indexing', href: '/dashboard/indexing', icon: SearchCheck },
      { label: 'SERP Snapshots', href: '/dashboard/serp-snapshots', icon: Camera },
    ],
  },
  {
    label: 'Content',
    icon: FileText,
    href: '/dashboard/content-engine',
    children: [
      { label: 'Content Engine', href: '/dashboard/content-engine', icon: Sparkles },
      { label: 'Blogs', href: '/dashboard/blogs', icon: Newspaper },
      { label: 'Suggestions', href: '/dashboard/content', icon: FileText },
      { label: 'GEO / AEO', href: '/dashboard/geo-aeo', icon: Target },
      { label: 'Semantic Search', href: '/dashboard/semantic', icon: Database },
    ],
  },
  {
    label: 'Site Health',
    icon: FileWarning,
    href: '/dashboard/audit',
    children: [
      { label: 'Audit Issues', href: '/dashboard/audit', icon: FileWarning },
      { label: 'Core Web Vitals', href: '/dashboard/core-web-vitals', icon: Gauge },
      { label: 'Technology', href: '/dashboard/technology', icon: Cpu },
      { label: 'Verification', href: '/dashboard/verification', icon: BadgeCheck },
      { label: 'Deployment', href: '/dashboard/deployment-verification', icon: BadgeCheck },
    ],
  },
  {
    label: 'Automation',
    icon: Bot,
    href: '/dashboard/operations',
    children: [
      { label: 'SEO Operations', href: '/dashboard/operations', icon: Activity },
      { label: 'SEO Brain', href: '/dashboard/seo-brain', icon: Bot },
      { label: 'Weekly Planner', href: '/dashboard/planner', icon: Bot },
      { label: 'Daily Briefing', href: '/dashboard/daily-briefing', icon: Sparkles },
      { label: 'Pending AI Fixes', href: '/dashboard/pending-fixes', icon: GitBranch },
    ],
  },
  {
    label: 'Code',
    icon: GitPullRequest,
    href: '/dashboard/code-review',
    children: [
      { label: 'Code Review', href: '/dashboard/code-review', icon: GitPullRequest },
      { label: 'Repo Patches', href: '/dashboard/repos', icon: GitBranch },
    ],
  },
  {
    label: 'Growth',
    icon: TrendingUp,
    href: '/dashboard/growth',
    children: [
      { label: 'SEO Growth', href: '/dashboard/growth', icon: TrendingUp },
      { label: 'Impact', href: '/dashboard/impact', icon: Activity },
      { label: 'Report', href: '/dashboard/report', icon: FileCheck2 },
    ],
  },
  {
    label: 'Project Setup',
    icon: Rocket,
    href: '/dashboard/setup',
  },
];

/**
 * Whether `pathname` is on `href`.
 *
 * `/dashboard` is an exact match because it is the prefix of every other page;
 * a `startsWith` test would light up Overview on every screen in the product.
 */
export function isActiveHref(pathname: string, href: string): boolean {
  return href === '/dashboard' ? pathname === href : pathname.startsWith(href);
}

/** The section `pathname` belongs to, or undefined on a page outside the nav. */
export function sectionForPath(pathname: string): NavSection | undefined {
  return navSections.find((section) =>
    section.children
      ? section.children.some((child) => isActiveHref(pathname, child.href))
      : isActiveHref(pathname, section.href)
  );
}
