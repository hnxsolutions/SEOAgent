import Link from 'next/link';
import { LayoutDashboard, LogIn, UserPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function HomePage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-xl rounded-lg border bg-white p-6 text-center shadow-sm">
        <p className="text-sm font-medium text-muted-foreground">Local MVP</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">AI SEO Agent</h1>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Button asChild type="button">
            <Link href="/dashboard">
              <LayoutDashboard className="mr-2 h-4 w-4" aria-hidden="true" />
              Go to Dashboard
            </Link>
          </Button>
          <Button asChild type="button" variant="outline">
            <Link href="/login">
              <LogIn className="mr-2 h-4 w-4" aria-hidden="true" />
              Login
            </Link>
          </Button>
          <Button asChild type="button" variant="outline">
            <Link href="/register">
              <UserPlus className="mr-2 h-4 w-4" aria-hidden="true" />
              Register
            </Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
