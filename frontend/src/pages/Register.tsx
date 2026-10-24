import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { errorText } from "../api/errors";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, SelectField, TextField } from "../components/ui";

export default function Register() {
  const { register, user } = useAuth();
  const navigate = useNavigate();
  const [role, setRole] = useState<"candidate" | "recruiter">("candidate");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await register({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        role,
        invite_code: role === "recruiter" ? invite : undefined,
      });
      navigate(homeFor(created.role), { replace: true });
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-12 max-w-md px-4">
      <h1 className="mb-1 text-center text-3xl font-bold text-indigo-800">Create your account</h1>
      <p className="mb-6 text-center text-sm text-slate-600">Candidates can apply to jobs. Recruiters manage hiring.</p>
      <Card>
        <form onSubmit={submit} className="space-y-4" noValidate>
          {error && <Alert tone="error">{error}</Alert>}
          <SelectField label="I am a" value={role} onChange={(e) => setRole(e.target.value as "candidate" | "recruiter")}>
            <option value="candidate">Candidate (looking for a job)</option>
            <option value="recruiter">Recruiter (hiring)</option>
          </SelectField>
          <TextField label="Full name" autoComplete="name" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            hint="At least 10 characters, with a letter and a number."
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {role === "recruiter" && (
            <TextField
              label="Recruiter invite code"
              required
              hint="Ask your administrator for the invite code."
              value={invite}
              onChange={(e) => setInvite(e.target.value)}
            />
          )}
          <Button type="submit" className="w-full" disabled={busy || !fullName || !email || !password}>
            {busy ? "Creating account…" : "Create account"}
          </Button>
        </form>
      </Card>
      <p className="mt-4 text-center text-sm text-slate-600">
        Already registered?{" "}
        <Link className="font-semibold text-indigo-800 underline" to="/login">
          Sign in
        </Link>
      </p>
    </div>
  );
}
