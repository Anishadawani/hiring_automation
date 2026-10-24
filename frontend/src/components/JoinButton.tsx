import { safeHref } from "../lib/format";

type Joinable = {
  id: number;
  join_method: "platform" | "external_link" | "phone" | "onsite";
  location?: string | null;
  status: string;
};

/** How to take part in an interview, depending on how the recruiter set it up. */
export function JoinButton({ interview }: { interview: Joinable }) {
  if (interview.status !== "scheduled") return null;
  const href = safeHref(interview.location);

  switch (interview.join_method) {
    case "external_link":
      return href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center rounded-md bg-indigo-700 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800"
        >
          Open meeting link
        </a>
      ) : (
        <span className="text-sm text-slate-700">Meeting details: {interview.location}</span>
      );
    case "phone":
      return <span className="text-sm text-slate-700">We will call: {interview.location}</span>;
    case "onsite":
      return <span className="text-sm text-slate-700">Location: {interview.location}</span>;
    default:
      return <span className="text-sm text-slate-700">The HireSense live room is added in Phase 6.</span>;
  }
}
