import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { RequireRole } from "../auth/RequireRole";
import { asUser, candidateUser, json, mockApi, recruiterUser, renderApp } from "../test/utils";
import Login from "./Login";
import Register from "./Register";

function Shell() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/jobs" element={<p>JOBS PAGE</p>} />
      <Route path="/recruiter" element={<p>RECRUITER HOME</p>} />
      <Route element={<RequireRole role="candidate" />}>
        <Route path="/profile" element={<p>PROFILE PAGE</p>} />
      </Route>
    </Routes>
  );
}

describe("Login", () => {
  it("signs a candidate in and sends them to jobs", async () => {
    const api = mockApi({ "POST /api/auth/login": { access_token: "tok", token_type: "bearer", user: candidateUser } });
    renderApp(<Shell />, { route: "/login" });
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "CorrectHorse9!");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("JOBS PAGE")).toBeInTheDocument();
    expect(api.called("POST /api/auth/login")[0].body).toEqual({ email: "ada@example.com", password: "CorrectHorse9!" });
    expect(sessionStorage.getItem("hiresense.token")).toBe("tok");
  });

  it("shows the server's message when the password is wrong", async () => {
    mockApi({ "POST /api/auth/login": () => json({ detail: "Incorrect email or password." }, 401) });
    renderApp(<Shell />, { route: "/login" });
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(sessionStorage.getItem("hiresense.token")).toBeNull();
  });

  it("keeps the button disabled until both fields are filled", async () => {
    mockApi({});
    renderApp(<Shell />, { route: "/login" });
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });
});

describe("Register", () => {
  it("asks for the invite code only when registering as a recruiter", async () => {
    mockApi({});
    renderApp(<Shell />, { route: "/register" });
    expect(screen.queryByLabelText("Recruiter invite code")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("I am a"), "recruiter");
    expect(screen.getByLabelText("Recruiter invite code")).toBeInTheDocument();
  });

  it("registers, signs in and goes to the right home page", async () => {
    const api = mockApi({
      "POST /api/auth/register": { ...recruiterUser },
      "POST /api/auth/login": { access_token: "tok", token_type: "bearer", user: recruiterUser },
    });
    renderApp(<Shell />, { route: "/register" });
    await userEvent.selectOptions(screen.getByLabelText("I am a"), "recruiter");
    await userEvent.type(screen.getByLabelText("Full name"), "Rae Recruiter");
    await userEvent.type(screen.getByLabelText("Email"), "rec@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "CorrectHorse9!");
    await userEvent.type(screen.getByLabelText("Recruiter invite code"), "abc123");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("RECRUITER HOME")).toBeInTheDocument();
    expect(api.called("POST /api/auth/register")[0].body).toMatchObject({ role: "recruiter", invite_code: "abc123" });
  });

  it("shows validation problems from the server", async () => {
    mockApi({
      "POST /api/auth/register": () => json({ detail: [{ loc: ["body", "password"], msg: "Value error, Password must contain at least one letter and one number." }] }, 422),
    });
    renderApp(<Shell />, { route: "/register" });
    await userEvent.type(screen.getByLabelText("Full name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "1234567890");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("password: Password must contain at least one letter and one number.");
  });
});

describe("RequireRole", () => {
  it("sends anonymous visitors to the login page", async () => {
    mockApi({});
    renderApp(<Shell />, { route: "/profile" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("lets the right role in", async () => {
    mockApi(asUser(candidateUser));
    renderApp(<Shell />, { route: "/profile", user: candidateUser });
    expect(await screen.findByText("PROFILE PAGE")).toBeInTheDocument();
  });

  it("sends the wrong role to their own home", async () => {
    mockApi(asUser(recruiterUser));
    renderApp(<Shell />, { route: "/profile", user: recruiterUser });
    await waitFor(() => expect(screen.getByText("RECRUITER HOME")).toBeInTheDocument());
  });

  it("signs out when the session is rejected", async () => {
    mockApi({ "GET /api/auth/me": () => json({ detail: "Not authenticated." }, 401) });
    renderApp(<Shell />, { route: "/profile", user: candidateUser });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("hiresense.token")).toBeNull();
  });
});
