import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, call } from "../../api/client";
import { errorText } from "../../api/errors";
import type { Attempt } from "../../api/types";
import { Alert, Button, Card, PageHeader, QueryState } from "../../components/ui";

type Draft = { text?: string; option?: number | null };
type SaveState = "idle" | "saving" | "saved" | "error";

export function formatClock(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TakeAssessment() {
  const attemptId = Number(useParams().attemptId);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () => call(api.GET("/api/candidate/attempts/{attempt_id}", { params: { path: { attempt_id: attemptId } } })),
    staleTime: Infinity,
  });
  const attempt = query.data;
  const submitted = attempt?.status === "submitted";

  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [loadedId, setLoadedId] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [deadline, setDeadline] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const timers = useRef(new Map<number, number>());
  const pending = useRef(0);

  // Copy what the server already saved into the editable drafts (once per attempt).
  useEffect(() => {
    if (!attempt || loadedId === attempt.attempt_id) return;
    const initial: Record<number, Draft> = {};
    for (const a of attempt.answers) initial[a.question_id] = { text: a.answer_text ?? undefined, option: a.selected_option };
    setDrafts(initial);
    setDeadline(attempt.seconds_remaining == null ? null : Date.now() + attempt.seconds_remaining * 1000);
    setLoadedId(attempt.attempt_id);
  }, [attempt, loadedId]);

  // A one-second clock, only while there is a deadline and the attempt is open.
  useEffect(() => {
    if (deadline == null || submitted) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [deadline, submitted]);

  const remaining = deadline == null ? null : Math.max(0, Math.ceil((deadline - now) / 1000));

  const refreshAttempt = useCallback(async () => {
    const fresh = await call(api.GET("/api/candidate/attempts/{attempt_id}", { params: { path: { attempt_id: attemptId } } }));
    queryClient.setQueryData<Attempt>(["attempt", attemptId], fresh);
  }, [attemptId, queryClient]);

  // When time runs out the server closes the attempt; ask it what happened.
  useEffect(() => {
    if (remaining === 0 && !submitted) void refreshAttempt().catch(() => undefined);
  }, [remaining, submitted, refreshAttempt]);

  const save = useCallback(
    async (questionId: number, body: { answer_text?: string | null; selected_option?: number | null }) => {
      pending.current += 1;
      setSaveState("saving");
      try {
        await call(
          api.PUT("/api/candidate/attempts/{attempt_id}/answers/{question_id}", {
            params: { path: { attempt_id: attemptId, question_id: questionId } },
            body,
          }),
        );
        setProblem(null);
        if (pending.current === 1) setSaveState("saved");
      } catch (e) {
        setSaveState("error");
        setProblem(errorText(e));
        if (e instanceof Error && "status" in e && (e as { status: number }).status === 409) void refreshAttempt().catch(() => undefined);
      } finally {
        pending.current -= 1;
      }
    },
    [attemptId, refreshAttempt],
  );

  function chooseOption(questionId: number, option: number) {
    setDrafts((d) => ({ ...d, [questionId]: { ...d[questionId], option } }));
    void save(questionId, { selected_option: option });
  }

  function typeText(questionId: number, text: string) {
    setDrafts((d) => ({ ...d, [questionId]: { ...d[questionId], text } }));
    setSaveState("saving");
    const old = timers.current.get(questionId);
    if (old) window.clearTimeout(old);
    timers.current.set(
      questionId,
      window.setTimeout(() => {
        timers.current.delete(questionId);
        void save(questionId, { answer_text: text });
      }, 800),
    );
  }

  useEffect(() => {
    const map = timers.current;
    return () => map.forEach((id) => window.clearTimeout(id));
  }, []);

  async function submit() {
    setSubmitting(true);
    setProblem(null);
    try {
      // Save anything still waiting in the typing delay first, so nothing is lost.
      const waiting = [...timers.current.keys()];
      for (const id of waiting) window.clearTimeout(timers.current.get(id));
      timers.current.clear();
      await Promise.all(waiting.map((id) => save(id, { answer_text: drafts[id]?.text ?? "" })));
      const result = await call(api.POST("/api/candidate/attempts/{attempt_id}/submit", { params: { path: { attempt_id: attemptId } } }));
      queryClient.setQueryData<Attempt>(["attempt", attemptId], result);
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setSubmitting(false);
      setConfirming(false);
    }
  }

  const answered = attempt
    ? attempt.questions.filter((q) => {
        const d = drafts[q.id];
        return d && (d.option != null || (d.text ?? "").trim() !== "");
      }).length
    : 0;

  const minutesLeft = remaining == null ? null : Math.ceil(remaining / 60);
  const announce = minutesLeft != null && [10, 5, 1].includes(minutesLeft) ? `${minutesLeft} minute${minutesLeft === 1 ? "" : "s"} remaining.` : "";

  return (
    <QueryState isLoading={query.isLoading || (!!attempt && loadedId !== attempt.attempt_id)} error={query.error} loadingLabel="Loading assessment…">
      {attempt && submitted && (
        <>
          <PageHeader title={attempt.title} />
          <Alert tone="success">
            Your assessment has been submitted. Thank you. The recruiter will review your answers.{" "}
            <Link className="font-semibold underline" to="/assessments">
              Back to assessments
            </Link>
          </Alert>
        </>
      )}
      {attempt && !submitted && (
        <>
          <PageHeader
            title={attempt.title}
            subtitle={`${attempt.total_questions} questions. Your answers are saved automatically as you go.`}
            actions={
              remaining != null ? (
                <div role="timer" aria-label="Time remaining" className={`rounded-md px-3 py-2 text-lg font-bold tabular-nums ${remaining < 300 ? "bg-red-100 text-red-900" : "bg-slate-200 text-slate-900"}`}>
                  {formatClock(remaining)}
                </div>
              ) : undefined
            }
          />
          <p className="sr-only" aria-live="polite">{announce}</p>

          {attempt.instructions && (
            <Card className="mb-6">
              <h2 className="mb-1 font-semibold">Instructions</h2>
              <p className="whitespace-pre-line text-sm text-slate-800">{attempt.instructions}</p>
            </Card>
          )}

          {problem && <Alert tone="error" className="mb-4">{problem}</Alert>}

          <ol className="space-y-5">
            {attempt.questions.map((q, index) => (
              <li key={q.id}>
                <Card>
                  {q.question_type === "multiple_choice" ? (
                    <fieldset>
                      <legend className="mb-3 font-medium">
                        <span className="mr-2 text-slate-500">{index + 1}.</span>
                        {q.prompt} <span className="text-xs font-normal text-slate-500">({q.max_points} point{q.max_points === 1 ? "" : "s"})</span>
                      </legend>
                      <div className="space-y-2">
                        {q.options.map((option, i) => (
                          <label key={i} className="flex cursor-pointer items-center gap-3 rounded-md p-2 text-sm hover:bg-slate-50">
                            <input
                              type="radio"
                              name={`q-${q.id}`}
                              className="h-4 w-4"
                              checked={drafts[q.id]?.option === i}
                              onChange={() => chooseOption(q.id, i)}
                            />
                            {option}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ) : (
                    <div>
                      <label htmlFor={`q-${q.id}`} className="mb-3 block font-medium">
                        <span className="mr-2 text-slate-500">{index + 1}.</span>
                        {q.prompt} <span className="text-xs font-normal text-slate-500">({q.max_points} point{q.max_points === 1 ? "" : "s"})</span>
                      </label>
                      <textarea
                        id={`q-${q.id}`}
                        rows={6}
                        maxLength={10000}
                        className="block w-full rounded-md border-0 px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-600"
                        value={drafts[q.id]?.text ?? ""}
                        onChange={(e) => typeText(q.id, e.target.value)}
                      />
                    </div>
                  )}
                </Card>
              </li>
            ))}
          </ol>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p role="status" className="text-sm text-slate-600">
              {saveState === "saving" && "Saving…"}
              {saveState === "saved" && "All changes saved."}
              {saveState === "error" && "Could not save. Your last change may be missing. We will retry when you keep typing."}
              {saveState === "idle" && "Answered " + answered + " of " + attempt.total_questions + "."}
            </p>
            {confirming ? (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>
                  You answered {answered} of {attempt.total_questions}. Submit now? You cannot change answers afterwards.
                </span>
                <Button disabled={submitting} onClick={submit}>
                  {submitting ? "Submitting…" : "Yes, submit"}
                </Button>
                <Button tone="secondary" onClick={() => setConfirming(false)}>
                  Keep working
                </Button>
              </div>
            ) : (
              <Button onClick={() => setConfirming(true)}>Submit assessment</Button>
            )}
          </div>
        </>
      )}
    </QueryState>
  );
}
