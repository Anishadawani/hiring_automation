import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, call } from "../../api/client";
import { Badge, Button, Card, EmptyState, PageHeader, Pagination, QueryState, SelectField, TextField } from "../../components/ui";
import { EMPLOYMENT_LABELS } from "../../lib/format";

const LIMIT = 10;
type Filters = { q: string; location: string; type: string };

export default function Jobs() {
  const [draft, setDraft] = useState<Filters>({ q: "", location: "", type: "" });
  const [filters, setFilters] = useState<Filters>(draft);
  const [offset, setOffset] = useState(0);

  const query = useQuery({
    queryKey: ["openings", filters, offset],
    queryFn: () =>
      call(
        api.GET("/api/openings", {
          params: {
            query: {
              q: filters.q || undefined,
              location: filters.location || undefined,
              employment_type: (filters.type || undefined) as "full_time" | undefined,
              limit: LIMIT,
              offset,
            },
          },
        }),
      ),
  });

  function search(event: FormEvent) {
    event.preventDefault();
    setOffset(0);
    setFilters(draft);
  }

  return (
    <>
      <PageHeader title="Open jobs" subtitle="Find a role and apply. You will need a profile and a resume." />
      <Card className="mb-6">
        <form onSubmit={search} className="grid gap-4 sm:grid-cols-4" role="search">
          <TextField label="Keyword" value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} />
          <TextField label="Location" value={draft.location} onChange={(e) => setDraft({ ...draft, location: e.target.value })} />
          <SelectField label="Type" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
            <option value="">Any</option>
            {Object.entries(EMPLOYMENT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
          <div className="flex items-end">
            <Button type="submit" className="w-full">
              Search
            </Button>
          </div>
        </form>
      </Card>

      <QueryState isLoading={query.isLoading} error={query.error} loadingLabel="Loading jobs…">
        {query.data && query.data.items.length === 0 ? (
          <EmptyState title="No jobs match your search">Try different keywords or clear the filters.</EmptyState>
        ) : (
          <>
            <p className="mb-3 text-sm text-slate-600" aria-live="polite">
              {query.data?.total} job{query.data?.total === 1 ? "" : "s"} found
            </p>
            <ul className="space-y-3">
              {query.data?.items.map((job) => (
                <li key={job.id}>
                  <Card className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold">
                        <Link className="text-indigo-800 hover:underline" to={`/jobs/${job.id}`}>
                          {job.title}
                        </Link>
                      </h2>
                      <p className="mt-1 text-sm text-slate-600">
                        {[job.department, job.location].filter(Boolean).join(" · ") || "Location not specified"}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Badge>{EMPLOYMENT_LABELS[job.employment_type] ?? job.employment_type}</Badge>
                        {job.required_skills.slice(0, 5).map((skill) => (
                          <Badge key={skill} tone="indigo">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    {job.has_applied ? <Badge tone="green">Applied</Badge> : <Link className="text-sm font-semibold text-indigo-800 underline" to={`/jobs/${job.id}`}>View and apply</Link>}
                  </Card>
                </li>
              ))}
            </ul>
            <Pagination total={query.data?.total ?? 0} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>
    </>
  );
}
