import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call } from "../../api/client";
import { errorText } from "../../api/errors";
import type { CandidateInterview } from "../../api/types";
import { JoinButton } from "../../components/JoinButton";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, QueryState } from "../../components/ui";
import { formatDateTime } from "../../lib/format";

const HOW: Record<CandidateInterview["join_method"], string> = {
  platform: "Video call in HireSense",
  external_link: "Video call (meeting link)",
  phone: "Phone call",
  onsite: "On site",
};

export default function Interviews() {
  const queryClient = useQueryClient();
  const interviews = useQuery({ queryKey: ["my-interviews"], queryFn: () => call(api.GET("/api/candidate/interviews")) });
  const notice = useQuery({ queryKey: ["consent-notice"], queryFn: () => call(api.GET("/api/interviews/consent-notice")) });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["my-interviews"] });
  const respond = useMutation({
    mutationFn: (v: { id: number; response: "confirmed" | "declined" }) =>
      call(api.POST("/api/candidate/interviews/{interview_id}/respond", { params: { path: { interview_id: v.id } }, body: { response: v.response } })),
    onSuccess: refresh,
  });
  const consent = useMutation({
    mutationFn: (v: { id: number; granted: boolean }) =>
      call(api.PUT("/api/candidate/interviews/{interview_id}/consent", { params: { path: { interview_id: v.id } }, body: { kind: "live_av", granted: v.granted } })),
    onSuccess: refresh,
  });

  const error = respond.error ?? consent.error;

  return (
    <>
      <PageHeader title="Interviews" subtitle="Invitations from recruiters appear here. Please confirm whether you can attend." />
      {error && <Alert tone="error" className="mb-4">{errorText(error)}</Alert>}
      <QueryState isLoading={interviews.isLoading} error={interviews.error}>
        {interviews.data?.length === 0 ? (
          <EmptyState title="No interviews yet">When a recruiter invites you, the details will appear here.</EmptyState>
        ) : (
          <ul className="space-y-4">
            {interviews.data?.map((iv) => (
              <li key={iv.id}>
                <Card className={iv.upcoming ? "" : "opacity-75"}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">{iv.job_title}</h2>
                      <p className="text-sm text-slate-700">
                        {formatDateTime(iv.scheduled_at)} · {iv.duration_minutes} minutes · {HOW[iv.join_method]}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {iv.status === "cancelled" && <Badge tone="red">Cancelled</Badge>}
                      {iv.status === "completed" && <Badge>Completed</Badge>}
                      {iv.status === "scheduled" && iv.my_response === "confirmed" && <Badge tone="green">You confirmed</Badge>}
                      {iv.status === "scheduled" && iv.my_response === "declined" && <Badge tone="red">You declined</Badge>}
                      {iv.status === "scheduled" && iv.my_response === "pending" && <Badge tone="amber">Needs your reply</Badge>}
                    </div>
                  </div>

                  {iv.status === "scheduled" && (
                    <div className="mt-4 space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Button disabled={respond.isPending || iv.my_response === "confirmed"} onClick={() => respond.mutate({ id: iv.id, response: "confirmed" })}>
                          I can attend
                        </Button>
                        <Button tone="secondary" disabled={respond.isPending || iv.my_response === "declined"} onClick={() => respond.mutate({ id: iv.id, response: "declined" })}>
                          I cannot attend
                        </Button>
                        <span className="ml-2">
                          <JoinButton interview={iv} />
                        </span>
                      </div>
                      <p className="text-xs text-slate-600">
                        If you need a different time, or any adjustment that would make the interview easier for you, please tell the recruiter.
                      </p>

                      {iv.join_method === "platform" && (
                        <div className="rounded-md bg-slate-50 p-4 ring-1 ring-slate-200">
                          <h3 className="font-semibold">Camera and microphone</h3>
                          {notice.data && <p className="mt-1 text-sm text-slate-800">{notice.data.live_av}</p>}
                          {notice.data && <p className="mt-2 text-xs text-slate-600">{notice.data.not_offered}</p>}
                          <p className="mt-3 text-sm" role="status">
                            {iv.live_av_consent === null && "You have not answered yet."}
                            {iv.live_av_consent === true && "You agreed to use your camera and microphone for this interview."}
                            {iv.live_av_consent === false && "You chose not to use your camera and microphone. Your application is not affected."}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Button disabled={consent.isPending || iv.live_av_consent === true} onClick={() => consent.mutate({ id: iv.id, granted: true })}>
                              I agree
                            </Button>
                            <Button tone="secondary" disabled={consent.isPending || iv.live_av_consent === false} onClick={() => consent.mutate({ id: iv.id, granted: false })}>
                              I do not agree
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
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
