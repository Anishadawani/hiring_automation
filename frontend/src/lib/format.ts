import type { Stage } from "../api/types";

/** Backend timestamps are UTC. If one arrives without a zone marker, treat it as UTC. */
export function parseDate(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parseDate(value));
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parseDate(value));
}

export const STAGE_LABELS: Record<Stage, string> = {
  applied: "Applied",
  under_review: "Under review",
  assessment: "Assessment",
  interview: "Interview",
  shortlisted: "Shortlisted",
  offer: "Offer",
  hired: "Hired",
  rejected: "Not moving forward",
  withdrawn: "Withdrawn",
};

export const STAGE_HELP: Record<Stage, string> = {
  applied: "We received your application.",
  under_review: "A recruiter is reviewing your application.",
  assessment: "You have an assessment to complete. See the Assessments page.",
  interview: "You are at the interview stage. See the Interviews page.",
  shortlisted: "You have been shortlisted. We will contact you about next steps.",
  offer: "An offer is being prepared.",
  hired: "Congratulations!",
  rejected: "The team decided not to move forward with this application.",
  withdrawn: "You withdrew this application.",
};

export const EMPLOYMENT_LABELS: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
};

export function minutesLabel(minutes: number | null | undefined): string {
  if (!minutes) return "No time limit";
  return minutes >= 60 && minutes % 60 === 0 ? `${minutes / 60} hour${minutes === 60 ? "" : "s"}` : `${minutes} minutes`;
}

/** Only http(s) links are ever rendered as links, so a pasted "javascript:..." can never run. */
export function safeHref(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function splitList(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}
