import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, call, uploadResume } from "../../api/client";
import { errorText } from "../../api/errors";
import type { ProfileUpdate } from "../../api/types";
import { Alert, Button, Card, PageHeader, QueryState, TextArea, TextField } from "../../components/ui";
import { formatDateTime, splitList } from "../../lib/format";

type Edu = { institution: string; degree: string; field_of_study: string; start_year: string; end_year: string };
type Exp = { company: string; title: string; start_date: string; end_date: string; description: string };
type Form = {
  headline: string;
  phone: string;
  location: string;
  summary: string;
  skills: string;
  education: Edu[];
  experience: Exp[];
};

const emptyEdu: Edu = { institution: "", degree: "", field_of_study: "", start_year: "", end_year: "" };
const emptyExp: Exp = { company: "", title: "", start_date: "", end_date: "", description: "" };

function toPayload(form: Form): ProfileUpdate {
  return {
    headline: form.headline.trim() || null,
    phone: form.phone.trim() || null,
    location: form.location.trim() || null,
    summary: form.summary.trim() || null,
    skills: splitList(form.skills),
    education: form.education
      .filter((e) => e.institution.trim() || e.degree.trim())
      .map((e) => ({
        institution: e.institution.trim(),
        degree: e.degree.trim(),
        field_of_study: e.field_of_study.trim() || null,
        start_year: e.start_year ? Number(e.start_year) : null,
        end_year: e.end_year ? Number(e.end_year) : null,
      })),
    experience: form.experience
      .filter((x) => x.company.trim() || x.title.trim())
      .map((x) => ({
        company: x.company.trim(),
        title: x.title.trim(),
        start_date: x.start_date,
        end_date: x.end_date || null,
        description: x.description.trim() || null,
      })),
  };
}

export default function Profile() {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => call(api.GET("/api/candidate/profile")) });
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const p = profile.data;
    if (!p || form) return;
    setForm({
      headline: p.headline ?? "",
      phone: p.phone ?? "",
      location: p.location ?? "",
      summary: p.summary ?? "",
      skills: p.skills.join(", "),
      education: p.education.map((e) => ({
        institution: e.institution,
        degree: e.degree,
        field_of_study: e.field_of_study ?? "",
        start_year: e.start_year?.toString() ?? "",
        end_year: e.end_year?.toString() ?? "",
      })),
      experience: p.experience.map((x) => ({
        company: x.company,
        title: x.title,
        start_date: x.start_date,
        end_date: x.end_date ?? "",
        description: x.description ?? "",
      })),
    });
  }, [profile.data, form]);

  const save = useMutation({
    mutationFn: (payload: ProfileUpdate) => call(api.PUT("/api/candidate/profile", { body: payload })),
    onSuccess: async () => {
      setSaved(true);
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
    },
  });
  const upload = useMutation({
    mutationFn: (file: File) => uploadResume(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["profile"] }),
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE("/api/candidate/resume")),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["profile"] }),
  });

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setSaved(false);
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (form) save.mutate(toPayload(form));
  }

  return (
    <>
      <PageHeader title="My profile" subtitle="Recruiters see this with your application. Keep it focused on skills and experience." />
      <QueryState isLoading={profile.isLoading || (!form && !profile.error)} error={profile.error}>
        {form && (
          <div className="space-y-6">
            <Card>
              <h2 className="mb-1 font-semibold">Resume</h2>
              <p className="mb-3 text-sm text-slate-600">PDF or plain text, up to 5 MB. Scanned images are not supported.</p>
              {upload.error && <Alert tone="error" className="mb-3">{errorText(upload.error)}</Alert>}
              {remove.error && <Alert tone="error" className="mb-3">{errorText(remove.error)}</Alert>}
              {profile.data?.resume_filename ? (
                <p className="mb-3 text-sm">
                  <strong>{profile.data.resume_filename}</strong>, uploaded {formatDateTime(profile.data.resume_uploaded_at)}
                </p>
              ) : (
                <Alert tone="warning" className="mb-3">No resume uploaded yet. You need one to apply.</Alert>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <label className="sr-only" htmlFor="resume-file">
                  Choose resume file
                </label>
                <input
                  id="resume-file"
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.txt,application/pdf,text/plain"
                  className="text-sm"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload.mutate(file);
                    e.target.value = "";
                  }}
                />
                {upload.isPending && <span role="status" className="text-sm text-slate-600">Uploading…</span>}
                {profile.data?.resume_filename && (
                  <Button tone="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
                    Remove resume
                  </Button>
                )}
              </div>
            </Card>

            <form onSubmit={submit} className="space-y-6">
              <Card className="space-y-4">
                <h2 className="font-semibold">About you</h2>
                <Alert tone="info">
                  Please do not include your age, photo, marital status, religion or other personal details that are unrelated
                  to the job. They are not needed and are never used to score you.
                </Alert>
                <div className="grid gap-4 sm:grid-cols-2">
                  <TextField label="Headline" maxLength={200} value={form.headline} onChange={(e) => update("headline", e.target.value)} />
                  <TextField label="Location" maxLength={200} value={form.location} onChange={(e) => update("location", e.target.value)} />
                  <TextField label="Phone" maxLength={40} value={form.phone} onChange={(e) => update("phone", e.target.value)} />
                  <TextField label="Skills" hint="Separate with commas, for example: Python, FastAPI, PostgreSQL" value={form.skills} onChange={(e) => update("skills", e.target.value)} />
                </div>
                <TextArea label="Summary" maxLength={4000} value={form.summary} onChange={(e) => update("summary", e.target.value)} />
              </Card>

              <Card className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">Education</h2>
                  <Button tone="secondary" onClick={() => update("education", [...form.education, emptyEdu])}>
                    Add education
                  </Button>
                </div>
                {form.education.length === 0 && <p className="text-sm text-slate-600">No education added.</p>}
                {form.education.map((row, i) => (
                  <fieldset key={i} className="grid gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-5">
                    <legend className="px-1 text-xs font-semibold text-slate-600">Education {i + 1}</legend>
                    <TextField label="Institution" value={row.institution} onChange={(e) => update("education", form.education.map((r, j) => (j === i ? { ...r, institution: e.target.value } : r)))} />
                    <TextField label="Degree" value={row.degree} onChange={(e) => update("education", form.education.map((r, j) => (j === i ? { ...r, degree: e.target.value } : r)))} />
                    <TextField label="Field of study" value={row.field_of_study} onChange={(e) => update("education", form.education.map((r, j) => (j === i ? { ...r, field_of_study: e.target.value } : r)))} />
                    <TextField label="Start year" inputMode="numeric" value={row.start_year} onChange={(e) => update("education", form.education.map((r, j) => (j === i ? { ...r, start_year: e.target.value } : r)))} />
                    <TextField label="End year" inputMode="numeric" value={row.end_year} onChange={(e) => update("education", form.education.map((r, j) => (j === i ? { ...r, end_year: e.target.value } : r)))} />
                    <div className="sm:col-span-5">
                      <Button tone="ghost" onClick={() => update("education", form.education.filter((_, j) => j !== i))}>
                        Remove education {i + 1}
                      </Button>
                    </div>
                  </fieldset>
                ))}
              </Card>

              <Card className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">Work experience</h2>
                  <Button tone="secondary" onClick={() => update("experience", [...form.experience, emptyExp])}>
                    Add experience
                  </Button>
                </div>
                {form.experience.length === 0 && <p className="text-sm text-slate-600">No experience added.</p>}
                {form.experience.map((row, i) => (
                  <fieldset key={i} className="grid gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-4">
                    <legend className="px-1 text-xs font-semibold text-slate-600">Experience {i + 1}</legend>
                    <TextField label="Company" value={row.company} onChange={(e) => update("experience", form.experience.map((r, j) => (j === i ? { ...r, company: e.target.value } : r)))} />
                    <TextField label="Job title" value={row.title} onChange={(e) => update("experience", form.experience.map((r, j) => (j === i ? { ...r, title: e.target.value } : r)))} />
                    <TextField label="Start date" type="date" value={row.start_date} onChange={(e) => update("experience", form.experience.map((r, j) => (j === i ? { ...r, start_date: e.target.value } : r)))} />
                    <TextField label="End date" type="date" hint="Leave empty if this is your current job." value={row.end_date} onChange={(e) => update("experience", form.experience.map((r, j) => (j === i ? { ...r, end_date: e.target.value } : r)))} />
                    <div className="sm:col-span-4">
                      <TextArea label="What you did" rows={2} value={row.description} onChange={(e) => update("experience", form.experience.map((r, j) => (j === i ? { ...r, description: e.target.value } : r)))} />
                    </div>
                    <div className="sm:col-span-4">
                      <Button tone="ghost" onClick={() => update("experience", form.experience.filter((_, j) => j !== i))}>
                        Remove experience {i + 1}
                      </Button>
                    </div>
                  </fieldset>
                ))}
              </Card>

              {save.error && <Alert tone="error">{errorText(save.error)}</Alert>}
              {saved && <Alert tone="success">Your profile was saved.</Alert>}
              <Button type="submit" disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Save profile"}
              </Button>
            </form>
          </div>
        )}
      </QueryState>
    </>
  );
}
