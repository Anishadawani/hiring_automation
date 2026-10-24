import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, call } from "../../api/client";
import { errorText } from "../../api/errors";
import type { CandidateTask } from "../../api/types";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, QueryState } from "../../components/ui";
import { minutesLabel } from "../../lib/format";

export default function Assessments() {
  const navigate = useNavigate();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => call(api.GET("/api/candidate/assessments")) });
  const start = useMutation({
    mutationFn: (task: CandidateTask) =>
      call(
        api.POST("/api/candidate/applications/{application_id}/assessments/{assessment_id}/start", {
          params: { path: { application_id: task.application_id, assessment_id: task.assessment_id } },
        }),
      ),
    onSuccess: (attempt) => navigate(`/assessments/take/${attempt.attempt_id}`),
  });

  return (
    <>
      <PageHeader title="Assessments" subtitle="Assessments appear here when a recruiter asks you to complete one." />
      {start.error && <Alert tone="error" className="mb-4">{errorText(start.error)}</Alert>}
      <QueryState isLoading={tasks.isLoading} error={tasks.error}>
        {tasks.data?.length === 0 ? (
          <EmptyState title="Nothing to complete right now">You will see an assessment here if a recruiter requests one.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {tasks.data?.map((task) => (
              <li key={`${task.application_id}-${task.assessment_id}`}>
                <Card className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">{task.title}</h2>
                    <p className="text-sm text-slate-600">
                      For {task.job_title} · {task.question_count} question{task.question_count === 1 ? "" : "s"} · {minutesLabel(task.time_limit_minutes)}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Badge tone="indigo">{task.kind}</Badge>
                      {task.status === "submitted" && <Badge tone="green">Submitted</Badge>}
                      {task.status === "in_progress" && <Badge tone="amber">In progress</Badge>}
                    </div>
                  </div>
                  {task.status === "submitted" ? (
                    <span className="text-sm text-slate-600">Thank you. The recruiter will review it.</span>
                  ) : (
                    <Button disabled={start.isPending} onClick={() => start.mutate(task)}>
                      {task.status === "in_progress" ? "Continue" : "Start"}
                    </Button>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </>
  );
}
