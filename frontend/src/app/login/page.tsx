'use client';

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LogIn } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { authAPI } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await authAPI.login(email, password);
      window.localStorage.setItem('access_token', response.data.access_token);
      window.localStorage.setItem('refresh_token', response.data.refresh_token);
      router.replace('/dashboard');
    } catch (requestError) {
      setError(errorMessage(requestError, 'Login failed. Check your email and password.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <section className="w-full max-w-md rounded-lg border bg-white p-6 shadow-sm">
        <div>
          <p className="text-sm font-medium text-muted-foreground">AI SEO Agent</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Login</h1>
        </div>

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
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>

          {error ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {error}
            </div>
          ) : null}

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            <LogIn className="mr-2 h-4 w-4" aria-hidden="true" />
            {isSubmitting ? 'Logging in' : 'Login'}
          </Button>
        </form>

        <div className="mt-5 flex items-center justify-between gap-3 text-sm">
          <Link href="/" className="font-medium text-slate-600 hover:text-slate-950">
            Home
          </Link>
          <Link href="/register" className="font-medium text-blue-700 hover:text-blue-800">
            Register
          </Link>
        </div>
      </section>
    </main>
  );
}

function errorMessage(error: unknown, fallback: string) {
  const responseError = error as { response?: { data?: { detail?: string } } };
  return responseError.response?.data?.detail ?? (error instanceof Error ? error.message : fallback);
}
