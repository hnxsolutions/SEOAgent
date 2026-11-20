import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: Date | string): string {
  return new Date(date).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Parse a timestamp from the API.
 *
 * The backend stores times with `datetime.utcnow()` in `timestamp without time
 * zone` columns, so what arrives on the wire is an ISO string carrying no zone
 * at all: "2026-10-07T11:10:18.327793". JavaScript reads a zone-less string as
 * *local* time, so a run started at 16:40 IST rendered as "11:10 AM" — every
 * time on the dashboard was five and a half hours behind, and a run that had
 * just started looked hours old.
 *
 * The values are UTC, so they are read as UTC. A string that does carry a zone
 * is left exactly as it is.
 */
export function parseApiDate(value: Date | string): Date {
  if (value instanceof Date) return value;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value.trim());
  return new Date(hasZone ? value : `${value.replace(' ', 'T')}Z`);
}

export function formatDateTime(date: Date | string): string {
  return parseApiDate(date).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + '...';
}