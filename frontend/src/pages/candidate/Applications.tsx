import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, call } from "../../api/client";
import { errorText } from "../../api/errors";
import { Alert, Button, Card, EmptyState, PageHeader, QueryState, StageBadge } from "../../components/ui";
import { formatDate, STAGE_HELP } from "../../lib/format";

const FINAL = new Set(["hired", "rejected", "withdrawn"]);

export default function Applications() {
  const queryClient = useQueryClient();
  const applied = (useLocation().state as { applied?: string } | null)?.applied;
  const [confirming, setConfirming] = useState<number | null>(null);

  const query = useQuery({ queryKey: ["applications"], queryFn: () => call(api.GET("/api/applications/mine")) });
  const withdraw = useMutation({
    mutationFn: (id: number) => call(api.POST("/api/applications/{application_id}/withdraw", { params: { path: { application_id: id } } })),
    onSuccess: () => {
      setConfirming(null);
      return queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  return (
    <>
      <PageHeader title="My applications" subtitle="Follow each application from submission to decision." />
      {applied && <Alert tone="success" className="mb-4">Your application for {applied} was submitted.</Alert>}
      {withdraw.error && <Alert tone="error" className="mb-4">{errorText(withdraw.error)}</Alert>}
      <QueryState isLoading={query.isLoading} error={query.error}>
        {query.data?.length === 0 ? (
          <EmptyState title="You have not applied to any jobs yet">
            <Link className="font-semibold text-indigo-800 underline" to="/jobs">
              Browse open jobs
            </Link>
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {query.data?.map((app) => (
              <li key={app.id}>
                <Card className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">{app.job_title}</h2>
                    <p className="text-xs text-slate-600">Applied {formatDate(app.created_at)}</p>
                    <p className="mt-2 text-sm text-slate-700">{STAGE_HELP[app.stage]}</p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <StageBadge stage={app.stage} />
                    {!FINAL.has(app.stage) &&
                      (confirming === app.id ? (
                        <div className="flex items-center gap-2 text-sm">
                          <span>Withdraw this application?</span>
                          <Button tone="danger" disabled={withdraw.isPending} onClick={() => withdraw.mutate(app.id)}>
                            Yes, withdraw
                          </Button>
                          <Button tone="secondary" onClick={() => setConfirming(null)}>
                            Keep it
                          </Button>
                        </div>
                      ) : (
                        <Button tone="ghost" onClick={() => setConfirming(app.id)}>
                          Withdraw
                        </Button>
                      ))}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </>
  );
}
