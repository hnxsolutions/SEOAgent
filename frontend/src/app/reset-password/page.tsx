'use client';

/**
 * Choose a new password using a reset link.
 *
 * The token is checked before the form is shown, so an expired or already-used
 * link says so immediately rather than after someone has typed a new password
 * twice. The check reveals nothing: the caller already holds the token and the
 * only answer is whether it still works.
 */

import { FormEvent, Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { KeyRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { authAPI } from '@/lib/api';

const MIN_PASSWORD_LENGTH = 8;

function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get('token') ?? '';

  const [checking, setChecking] = useState(true);
  const [tokenValid, setTokenValid] = useState(false);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setChecking(false);
      setTokenValid(false);
      return;
    }
    authAPI
      .validateResetToken(token)
      .then((response) => {
        if (!cancelled) setTokenValid(Boolean(response.data?.valid));
      })
      .catch(() => {
        if (!cancelled) setTokenValid(false);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    // Checked here as well as on the server. The server is what enforces it;
    // this just avoids a round trip to be told something obvious.
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Choose a password of at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      await authAPI.resetPassword(token, password);
      setDone(true);
      // Straight to login — the token is spent, so there is nothing to come back to.
      setTimeout(() => router.replace('/login'), 2200);
    } catch (requestError) {
      setError(errorMessage(requestError, 'Could not reset your password. Request a new link.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <section className="w-full max-w-md rounded-lg border bg-white p-6 shadow-sm">
        <div>
          <p className="text-sm font-medium text-muted-foreground">AI SEO Agent</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Choose a new password</h1>
        </div>

        {checking ? (
          <p className="mt-6 text-sm text-muted-foreground">Checking your reset link…</p>
        ) : done ? (
          <div className="mt-6 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-900">
            Your password has been updated. Taking you to the login page…
          </div>
        ) : !tokenValid ? (
          <div className="mt-6 space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
              This reset link is invalid or has expired. Links work once and last 30
              minutes.
            </div>
            <Link href="/forgot-password">
              <Button className="w-full">Request a new link</Button>
            </Link>
          </div>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="password">New password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={MIN_PASSWORD_LENGTH}
              />
              <p className="text-xs text-muted-foreground">
                At least {MIN_PASSWORD_LENGTH} characters.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm">Confirm new password</Label>
              <Input
                id="confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                required
              />
            </div>

            {error ? (
              <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                {error}
              </div>
            ) : null}

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              <KeyRound className="mr-2 h-4 w-4" aria-hidden="true" />
              {isSubmitting ? 'Updating' : 'Update password'}
            </Button>
          </form>
        )}

        <div className="mt-5 text-sm">
          <Link href="/login" className="font-medium text-slate-600 hover:text-slate-950">
            Back to login
          </Link>
        </div>
      </section>
    </main>
  );
}

export default function ResetPasswordPage() {
  // useSearchParams needs a Suspense boundary for a statically rendered route.
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center bg-slate-50" />}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function errorMessage(error: unknown, fallback: string) {
  const responseError = error as { response?: { data?: { detail?: unknown } } };
  const detail = responseError.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return error instanceof Error ? error.message : fallback;
}
