import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, call } from "../../api/client";
import { errorText } from "../../api/errors";
import { Alert, Badge, Button, Card, PageHeader, QueryState, TextArea } from "../../components/ui";
import { EMPLOYMENT_LABELS } from "../../lib/format";

export default function JobDetail() {
  const jobId = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [cover, setCover] = useState("");

  const job = useQuery({
    queryKey: ["opening", jobId],
    queryFn: () => call(api.GET("/api/openings/{job_id}", { params: { path: { job_id: jobId } } })),
  });
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => call(api.GET("/api/candidate/profile")),
  });

  const apply = useMutation({
    mutationFn: () => call(api.POST("/api/applications", { body: { job_id: jobId, cover_letter: cover.trim() || null } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
      await queryClient.invalidateQueries({ queryKey: ["openings"] });
      navigate("/applications", { state: { applied: job.data?.title } });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    apply.mutate();
  }

  const hasResume = Boolean(profile.data?.resume_filename);

  return (
    <QueryState isLoading={job.isLoading} error={job.error} loadingLabel="Loading job…">
      {job.data && (
        <>
          <PageHeader
            title={job.data.title}
            subtitle={[job.data.department, job.data.location].filter(Boolean).join(" · ")}
            actions={<Badge>{EMPLOYMENT_LABELS[job.data.employment_type] ?? job.data.employment_type}</Badge>}
          />
          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <h2 className="mb-2 font-semibold">About the role</h2>
              <p className="whitespace-pre-line text-sm text-slate-800">{job.data.description}</p>
              <h3 className="mb-2 mt-5 font-semibold">Required skills</h3>
              <div className="flex flex-wrap gap-2">
                {job.data.required_skills.map((s) => (
                  <Badge key={s} tone="indigo">
                    {s}
                  </Badge>
                ))}
              </div>
              {job.data.preferred_skills.length > 0 && (
                <>
                  <h3 className="mb-2 mt-5 font-semibold">Nice to have</h3>
                  <div className="flex flex-wrap gap-2">
                    {job.data.preferred_skills.map((s) => (
                      <Badge key={s}>{s}</Badge>
                    ))}
                  </div>
                </>
              )}
              {job.data.min_years_experience > 0 && (
                <p className="mt-5 text-sm text-slate-700">Minimum experience: {job.data.min_years_experience} years</p>
              )}
            </Card>

            <Card>
              <h2 className="mb-3 font-semibold">Apply</h2>
              {job.data.has_applied ? (
                <Alert tone="success">
                  You have already applied.{" "}
                  <Link className="font-semibold underline" to="/applications">
                    Track your application
                  </Link>
                </Alert>
              ) : (
                <form onSubmit={submit} className="space-y-4">
                  {!profile.isLoading && !hasResume && (
                    <Alert tone="warning">
                      Upload your resume before applying.{" "}
                      <Link className="font-semibold underline" to="/profile">
                        Go to my profile
                      </Link>
                    </Alert>
                  )}
                  {apply.error && <Alert tone="error">{errorText(apply.error)}</Alert>}
                  <TextArea label="Cover letter (optional)" maxLength={3000} value={cover} onChange={(e) => setCover(e.target.value)} />
                  <p className="text-xs text-slate-600">
                    Recruiters may use AI tools to help prepare for reviewing your application. If they do, your resume text is
                    sent to the AI provider with email addresses and phone numbers removed. AI never makes hiring decisions: a
                    person does.
                  </p>
                  <Button type="submit" className="w-full" disabled={apply.isPending || !hasResume}>
                    {apply.isPending ? "Submitting…" : "Submit application"}
                  </Button>
                </form>
              )}
            </Card>
          </div>
        </>
      )}
    </QueryState>
  );
}
