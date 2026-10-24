import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { asUser, candidateUser, json, mockApi, renderApp } from "../../test/utils";
import Applications from "./Applications";
import Interviews from "./Interviews";
import JobDetail from "./JobDetail";
import Jobs from "./Jobs";
import Profile from "./Profile";
import TakeAssessment, { formatClock } from "./TakeAssessment";

const opening = {
  id: 7, title: "Backend Engineer", department: "Engineering", location: "Indore", employment_type: "full_time",
  description: "Build and maintain APIs.", required_skills: ["Python", "FastAPI"], preferred_skills: ["Docker"],
  min_years_experience: 2, created_at: "2026-01-01T00:00:00Z", has_applied: false,
};
const profile = (resume: string | null) => ({
  headline: null, phone: null, location: null, summary: null, skills: [], education: [], experience: [],
  resume_filename: resume, resume_uploaded_at: resume ? "2026-02-01T00:00:00Z" : null, updated_at: "2026-02-01T00:00:00Z",
});

describe("Jobs", () => {
  it("lists open jobs and searches with the keyword", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/openings": { items: [opening, { ...opening, id: 8, title: "Data Analyst", has_applied: true }], total: 2 },
    });
    renderApp(<Jobs />, { user: candidateUser });
    expect(await screen.findByRole("link", { name: "Backend Engineer" })).toHaveAttribute("href", "/jobs/7");
    expect(screen.getByText("2 jobs found")).toBeInTheDocument();
    expect(screen.getByText("Applied")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Keyword"), "python");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.called("GET /api/openings").some((c) => c.search.includes("q=python"))).toBe(true));
  });

  it("shows an empty state and an error message", async () => {
    mockApi({ ...asUser(candidateUser), "GET /api/openings": { items: [], total: 0 } });
    const { unmount } = renderApp(<Jobs />, { user: candidateUser });
    expect(await screen.findByText("No jobs match your search")).toBeInTheDocument();
    unmount();

    mockApi({ ...asUser(candidateUser), "GET /api/openings": () => json({ detail: "Database unavailable." }, 503) });
    renderApp(<Jobs />, { user: candidateUser });
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable.");
  });
});

describe("JobDetail", () => {
  function page() {
    return (
      <Routes>
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/applications" element={<p>MY APPLICATIONS</p>} />
      </Routes>
    );
  }

  it("blocks applying until a resume is uploaded", async () => {
    mockApi({ ...asUser(candidateUser), "GET /api/openings/7": opening, "GET /api/candidate/profile": profile(null) });
    renderApp(page(), { route: "/jobs/7", user: candidateUser });
    expect(await screen.findByText(/Upload your resume before applying/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit application" })).toBeDisabled();
  });

  it("submits the application and tells the candidate about AI assistance honestly", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/openings/7": opening,
      "GET /api/candidate/profile": profile("cv.pdf"),
      "POST /api/applications": { id: 1, job_id: 7, job_title: "Backend Engineer", stage: "applied", cover_letter: "Hello", created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z" },
    });
    renderApp(page(), { route: "/jobs/7", user: candidateUser });
    expect(await screen.findByText(/AI never makes hiring decisions/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Cover letter (optional)"), "Hello");
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit application" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
    expect(await screen.findByText("MY APPLICATIONS")).toBeInTheDocument();
    expect(api.called("POST /api/applications")[0].body).toEqual({ job_id: 7, cover_letter: "Hello" });
  });

  it("shows the server's reason when applying fails", async () => {
    mockApi({
      ...asUser(candidateUser),
      "GET /api/openings/7": opening,
      "GET /api/candidate/profile": profile("cv.pdf"),
      "POST /api/applications": () => json({ detail: "You have already applied to this job." }, 409),
    });
    renderApp(page(), { route: "/jobs/7", user: candidateUser });
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit application" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You have already applied to this job.");
  });
});

describe("Applications", () => {
  const app = (id: number, stage: string) => ({ id, job_id: id, job_title: `Job ${id}`, stage, cover_letter: null, created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z" });

  it("shows plain-language status and never exposes scores", async () => {
    mockApi({ ...asUser(candidateUser), "GET /api/applications/mine": [app(1, "under_review"), app(2, "rejected")] });
    renderApp(<Applications />, { user: candidateUser });
    expect(await screen.findByText("A recruiter is reviewing your application.")).toBeInTheDocument();
    expect(screen.getByText("The team decided not to move forward with this application.")).toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });

  it("asks before withdrawing", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/applications/mine": [app(1, "applied"), app(2, "withdrawn")],
      "POST /api/applications/1/withdraw": app(1, "withdrawn"),
    });
    renderApp(<Applications />, { user: candidateUser });
    const withdrawButtons = await screen.findAllByRole("button", { name: "Withdraw" });
    expect(withdrawButtons).toHaveLength(1); // finished applications cannot be withdrawn
    await userEvent.click(withdrawButtons[0]);
    expect(api.called("POST /api/applications/1/withdraw")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Yes, withdraw" }));
    await waitFor(() => expect(api.called("POST /api/applications/1/withdraw")).toHaveLength(1));
  });
});

describe("Profile", () => {
  it("saves skills as a clean list", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/profile": profile("cv.pdf"),
      "PUT /api/candidate/profile": profile("cv.pdf"),
    });
    renderApp(<Profile />, { user: candidateUser });
    const skills = await screen.findByLabelText("Skills");
    await userEvent.type(skills, "Python, ,FastAPI");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByText("Your profile was saved.")).toBeInTheDocument();
    expect(api.called("PUT /api/candidate/profile")[0].body).toMatchObject({ skills: ["Python", "FastAPI"], education: [], experience: [] });
  });
});

describe("TakeAssessment", () => {
  const attempt = (overrides = {}) => ({
    attempt_id: 5, assessment_id: 3, application_id: 1, title: "Backend skills check", kind: "technical",
    instructions: "Answer every question.", time_limit_minutes: 30, status: "in_progress",
    started_at: "2026-02-01T00:00:00Z", deadline: "2026-02-01T00:30:00Z", seconds_remaining: 125,
    total_questions: 2, answered_count: 0,
    questions: [
      { id: 11, position: 1, prompt: "Which status code means Not Found?", question_type: "multiple_choice", options: ["200", "404", "500"], max_points: 2 },
      { id: 12, position: 2, prompt: "Explain threads versus processes.", question_type: "free_text", options: [], max_points: 6 },
    ],
    answers: [], ...overrides,
  });
  const page = () => (
    <Routes>
      <Route path="/assessments/take/:attemptId" element={<TakeAssessment />} />
    </Routes>
  );

  it("shows the timer, instructions and accessible question groups", async () => {
    mockApi({ ...asUser(candidateUser), "GET /api/candidate/attempts/5": attempt() });
    renderApp(page(), { route: "/assessments/take/5", user: candidateUser });
    expect(await screen.findByRole("timer")).toHaveTextContent(/^2:0\d$/);
    expect(screen.getByText("Answer every question.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Which status code means Not Found/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/Explain threads versus processes/)).toBeInTheDocument();
    // The candidate never sees correct answers or scores.
    expect(document.body.textContent).not.toMatch(/correct|rubric/i);
  });

  it("saves a multiple-choice answer immediately and a text answer after a short pause", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/attempts/5": attempt(),
      "PUT /api/candidate/attempts/5/answers/11": { question_id: 11, answer_text: null, selected_option: 1 },
      "PUT /api/candidate/attempts/5/answers/12": { question_id: 12, answer_text: "x", selected_option: null },
    });
    renderApp(page(), { route: "/assessments/take/5", user: candidateUser });
    await userEvent.click(await screen.findByLabelText("404"));
    await waitFor(() => expect(api.called("PUT /api/candidate/attempts/5/answers/11")[0]?.body).toEqual({ selected_option: 1 }));

    await userEvent.type(screen.getByLabelText(/Explain threads/), "Threads share memory.");
    expect(api.called("PUT /api/candidate/attempts/5/answers/12")).toHaveLength(0); // still inside the typing pause
    await waitFor(() => expect(api.called("PUT /api/candidate/attempts/5/answers/12")).toHaveLength(1), { timeout: 3000 });
    expect(api.called("PUT /api/candidate/attempts/5/answers/12")[0].body).toEqual({ answer_text: "Threads share memory." });
    expect(await screen.findByText("All changes saved.")).toBeInTheDocument();
  });

  it("restores saved answers and warns when saving fails", async () => {
    mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/attempts/5": attempt({ answers: [{ question_id: 11, answer_text: null, selected_option: 2 }] }),
      "PUT /api/candidate/attempts/5/answers/11": () => json({ detail: "This assessment was submitted." }, 409),
    });
    renderApp(page(), { route: "/assessments/take/5", user: candidateUser });
    expect(await screen.findByLabelText("500")).toBeChecked();
    await userEvent.click(screen.getByLabelText("200"));
    expect(await screen.findByRole("alert")).toHaveTextContent("This assessment was submitted.");
  });

  it("asks for confirmation, then submits and shows the thank-you page", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/attempts/5": attempt(),
      "POST /api/candidate/attempts/5/submit": attempt({ status: "submitted", seconds_remaining: null }),
      "GET /api/candidate/assessments": [],
    });
    renderApp(page(), { route: "/assessments/take/5", user: candidateUser });
    await userEvent.click(await screen.findByRole("button", { name: "Submit assessment" }));
    expect(screen.getByText(/You answered 0 of 2/)).toBeInTheDocument();
    expect(api.called("POST /api/candidate/attempts/5/submit")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Yes, submit" }));
    expect(await screen.findByText(/Your assessment has been submitted/)).toBeInTheDocument();
  });

  it("formats the clock", () => {
    expect(formatClock(125)).toBe("2:05");
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(3600)).toBe("60:00");
  });
});

describe("Interviews", () => {
  const interview = (overrides = {}) => ({
    id: 9, application_id: 1, job_title: "Backend Engineer", scheduled_at: "2030-03-01T10:00:00Z", duration_minutes: 45,
    mode: "video", location: null, status: "scheduled", join_method: "platform", my_response: "pending",
    live_av_consent: null, upcoming: true, ...overrides,
  });
  const notice = { version: "2026-10-1", live_av: "Your camera and microphone are used only during this live interview.", not_offered: "Recording and transcription are not available in this version of HireSense." };

  it("shows the consent notice and records a clear yes or no", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/interviews": [interview()],
      "GET /api/interviews/consent-notice": notice,
      "PUT /api/candidate/interviews/9/consent": interview({ live_av_consent: true }),
    });
    renderApp(<Interviews />, { user: candidateUser });
    expect(await screen.findByText(/used only during this live interview/)).toBeInTheDocument();
    expect(screen.getByText(/Recording and transcription are not available/)).toBeInTheDocument();
    expect(screen.getByText("You have not answered yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    await waitFor(() => expect(api.called("PUT /api/candidate/interviews/9/consent")[0]?.body).toEqual({ kind: "live_av", granted: true }));
  });

  it("lets the candidate confirm or decline", async () => {
    const api = mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/interviews": [interview({ join_method: "phone", mode: "phone", location: "+91 98765 43210" })],
      "GET /api/interviews/consent-notice": notice,
      "POST /api/candidate/interviews/9/respond": interview({ my_response: "declined" }),
    });
    renderApp(<Interviews />, { user: candidateUser });
    expect(await screen.findByText("We will call: +91 98765 43210")).toBeInTheDocument();
    expect(screen.queryByText("Camera and microphone")).not.toBeInTheDocument(); // phone interviews need no camera consent
    await userEvent.click(screen.getByRole("button", { name: "I cannot attend" }));
    await waitFor(() => expect(api.called("POST /api/candidate/interviews/9/respond")[0]?.body).toEqual({ response: "declined" }));
  });

  it("never turns a dangerous meeting link into a clickable link", async () => {
    mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/interviews": [interview({ join_method: "external_link", mode: "video", location: "javascript:alert(1)" })],
      "GET /api/interviews/consent-notice": notice,
    });
    renderApp(<Interviews />, { user: candidateUser });
    expect(await screen.findByText(/Meeting details: javascript:alert\(1\)/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /meeting link/i })).not.toBeInTheDocument();
  });

  it("opens a safe https link in a new tab without leaking the opener", async () => {
    mockApi({
      ...asUser(candidateUser),
      "GET /api/candidate/interviews": [interview({ join_method: "external_link", mode: "video", location: "https://meet.example.com/abc" })],
      "GET /api/interviews/consent-notice": notice,
    });
    renderApp(<Interviews />, { user: candidateUser });
    const link = await screen.findByRole("link", { name: "Open meeting link" });
    expect(link).toHaveAttribute("href", "https://meet.example.com/abc");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(link.closest("li")!).queryByText("Camera and microphone")).not.toBeInTheDocument();
  });
});
