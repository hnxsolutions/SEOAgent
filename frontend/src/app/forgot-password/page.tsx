'use client';

/**
 * Request a password reset link.
 *
 * The success state is shown for *every* submitted address, including ones with
 * no account. The backend returns an identical response either way, and the UI
 * must not undo that by rendering something different — a page that said "no
 * account found" would hand an attacker the account list the API deliberately
 * withholds.
 */

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { Mail } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { authAPI } from '@/lib/api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await authAPI.forgotPassword(email.trim());
      setSent(true);
    } catch {
      // Only a transport failure can land here — the endpoint returns 200 for
      // any address. Deliberately generic so a server-side problem cannot be
      // read as "this address does not exist".
      setError('Could not reach the server. Please try again in a moment.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <section className="w-full max-w-md rounded-lg border bg-white p-6 shadow-sm">
        <div>
          <p className="text-sm font-medium text-muted-foreground">AI SEO Agent</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Forgot password</h1>
        </div>

        {sent ? (
          <div className="mt-6 space-y-4">
            <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-900">
              If an account exists for that email, a password reset link has been sent.
              The link works once and expires in 30 minutes.
            </div>
            <p className="text-sm text-muted-foreground">
              Nothing arrived? Check spam, then try again — requesting a new link
              cancels the previous one.
            </p>
            <Button variant="outline" className="w-full" onClick={() => setSent(false)}>
              Use a different email
            </Button>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm text-muted-foreground">
              Enter the email you sign in with and we will send you a link to choose a
              new password.
            </p>

            <form className="mt-6 space-y-4" onSubmit={onSubmit}>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </div>

              {error ? (
                <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  {error}
                </div>
              ) : null}

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                <Mail className="mr-2 h-4 w-4" aria-hidden="true" />
                {isSubmitting ? 'Sending' : 'Send reset link'}
              </Button>
            </form>
          </>
        )}

        <div className="mt-5 flex items-center justify-between gap-3 text-sm">
          <Link href="/login" className="font-medium text-slate-600 hover:text-slate-950">
            Back to login
          </Link>
          <Link href="/register" className="font-medium text-blue-700 hover:text-blue-800">
            Register
          </Link>
        </div>
      </section>
    </main>
  );
}
