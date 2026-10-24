export type NavLinkItem = { to: string; label: string };

export const NAV: Record<"candidate" | "recruiter", NavLinkItem[]> = {
  candidate: [
    { to: "/jobs", label: "Jobs" },
    { to: "/applications", label: "My applications" },
    { to: "/assessments", label: "Assessments" },
    { to: "/interviews", label: "Interviews" },
    { to: "/profile", label: "My profile" },
  ],
  recruiter: [],
};
