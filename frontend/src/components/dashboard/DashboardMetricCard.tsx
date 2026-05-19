import type { LucideIcon } from 'lucide-react';
import { ArrowUpRight } from 'lucide-react';
import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export function DashboardMetricCard({
  title,
  value,
  detail,
  icon: Icon,
  href,
  tone = 'blue',
}: {
  title: string;
  value: string | number;
  detail?: string;
  icon: LucideIcon;
  href?: string;
  tone?: 'blue' | 'emerald' | 'amber' | 'rose' | 'slate';
}) {
  const card = (
    <Card className="h-full rounded-lg transition-colors hover:border-slate-300">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 p-5 pb-3">
        <div>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {title}
          </CardTitle>
        </div>
        <span
          className={cn(
            'flex h-9 w-9 items-center justify-center rounded-md',
            toneStyles[tone]
          )}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </CardHeader>
      <CardContent className="p-5 pt-0">
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-3xl font-semibold tracking-normal">{value}</div>
            {detail ? (
              <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
            ) : null}
          </div>
          {href ? <ArrowUpRight className="h-4 w-4 text-muted-foreground" /> : null}
        </div>
      </CardContent>
    </Card>
  );

  if (!href) return card;

  return (
    <Link href={href} className="block h-full focus:outline-none focus:ring-2 focus:ring-ring">
      {card}
    </Link>
  );
}

const toneStyles = {
  blue: 'bg-blue-50 text-blue-700',
  emerald: 'bg-emerald-50 text-emerald-700',
  amber: 'bg-amber-50 text-amber-700',
  rose: 'bg-rose-50 text-rose-700',
  slate: 'bg-slate-100 text-slate-700',
};
