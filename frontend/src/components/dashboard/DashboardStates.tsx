import { AlertCircle, Loader2 } from 'lucide-react';
import type React from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function LoadingBlock({ label = 'Loading data' }: { label?: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-lg border bg-white p-6 text-sm text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed bg-white p-8 text-center">
      <h3 className="text-sm font-semibold">{title}</h3>
      {description ? (
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = 'Something did not load',
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <div className="flex gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <p className="font-semibold">{title}</p>
          {message ? <p className="mt-1 text-rose-700">{message}</p> : null}
          {onRetry ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3 border-rose-200 bg-white text-rose-700 hover:bg-rose-100"
              onClick={onRetry}
            >
              Retry
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ActionNotice({
  message,
  tone = 'success',
  className,
}: {
  message?: string;
  tone?: 'success' | 'error';
  className?: string;
}) {
  if (!message) return null;
  return (
    <div
      className={cn(
        'rounded-md border px-3 py-2 text-sm',
        tone === 'success'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
          : 'border-rose-200 bg-rose-50 text-rose-800',
        className
      )}
    >
      {message}
    </div>
  );
}
