import { useId, type ComponentProps, type ReactNode } from "react";
import { STAGE_LABELS } from "../lib/format";
import type { Stage } from "../api/types";

type Tone = "indigo" | "green" | "amber" | "red" | "slate";

const BUTTON_TONES = {
  primary: "bg-indigo-700 text-white hover:bg-indigo-800 disabled:bg-indigo-300",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-100 disabled:text-slate-400",
  danger: "bg-red-700 text-white hover:bg-red-800 disabled:bg-red-300",
  ghost: "text-indigo-800 hover:bg-indigo-50 disabled:text-slate-400",
};

export function Button({
  tone = "primary",
  className = "",
  type = "button",
  ...props
}: ComponentProps<"button"> & { tone?: keyof typeof BUTTON_TONES }) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${BUTTON_TONES[tone]} ${className}`}
      {...props}
    />
  );
}

export function Card({ className = "", ...props }: ComponentProps<"section">) {
  return <section className={`rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200 ${className}`} {...props} />;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const ALERT_TONES: Record<"error" | "success" | "info" | "warning", string> = {
  error: "bg-red-50 text-red-900 ring-red-200",
  success: "bg-green-50 text-green-900 ring-green-200",
  info: "bg-indigo-50 text-indigo-900 ring-indigo-200",
  warning: "bg-amber-50 text-amber-900 ring-amber-200",
};

export function Alert({
  tone = "info",
  children,
  className = "",
}: {
  tone?: keyof typeof ALERT_TONES;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md px-4 py-3 text-sm ring-1 ${ALERT_TONES[tone]} ${className}`}
    >
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-8 text-sm text-slate-600">
      <span
        aria-hidden="true"
        className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-700"
      />
      {label}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <p className="font-semibold text-slate-800">{title}</p>
      {children && <div className="mt-2 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

const BADGE_TONES: Record<Tone, string> = {
  indigo: "bg-indigo-100 text-indigo-900",
  green: "bg-green-100 text-green-900",
  amber: "bg-amber-100 text-amber-900",
  red: "bg-red-100 text-red-900",
  slate: "bg-slate-200 text-slate-800",
};

export function Badge({ tone = "slate", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

const STAGE_TONES: Record<Stage, Tone> = {
  applied: "slate",
  under_review: "indigo",
  assessment: "amber",
  interview: "amber",
  shortlisted: "green",
  offer: "green",
  hired: "green",
  rejected: "red",
  withdrawn: "slate",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return <Badge tone={STAGE_TONES[stage]}>{STAGE_LABELS[stage]}</Badge>;
}

type FieldShared = { label: string; hint?: string; error?: string };

function describedBy(id: string, hint?: string, error?: string) {
  return [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
}

function FieldFrame({ id, label, hint, error, children }: FieldShared & { id: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-slate-800">
        {label}
      </label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-slate-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

const CONTROL =
  "block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 disabled:bg-slate-100";

export function TextField({ label, hint, error, ...props }: FieldShared & ComponentProps<"input">) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <input id={id} className={CONTROL} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...props} />
    </FieldFrame>
  );
}

export function TextArea({ label, hint, error, ...props }: FieldShared & ComponentProps<"textarea">) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <textarea id={id} rows={4} className={CONTROL} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...props} />
    </FieldFrame>
  );
}

export function SelectField({ label, hint, error, children, ...props }: FieldShared & ComponentProps<"select">) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <select id={id} className={CONTROL} aria-describedby={describedBy(id, hint, error)} {...props}>
        {children}
      </select>
    </FieldFrame>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm">
      <Button tone="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Previous
      </Button>
      <span aria-live="polite">
        Page {page} of {pages}
      </span>
      <Button tone="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Next
      </Button>
    </nav>
  );
}

export function QueryState({
  isLoading,
  error,
  children,
  loadingLabel,
}: {
  isLoading: boolean;
  error: unknown;
  children: ReactNode;
  loadingLabel?: string;
}) {
  if (isLoading) return <Spinner label={loadingLabel} />;
  if (error) return <Alert tone="error">{error instanceof Error ? error.message : "Something went wrong."}</Alert>;
  return <>{children}</>;
}
