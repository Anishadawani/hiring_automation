# AI Hiring Automation (Claude)

Automates the first pass of resume screening. A resume and a job description go in; a structured result
(match score, recommendation, matched/missing skills, summary, interview questions) comes out.

Two parts:

1. **`app/`** - FastAPI service that calls the Claude API (Python, pydantic validation, tests, Docker).
2. **`n8n/`** - importable n8n workflow: Webhook -> Claude -> parse -> log to Google Sheets.

## Run the API locally
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key
uvicorn app.main:app --reload
# open http://localhost:8000/docs
curl -X POST localhost:8000/screen -F "job_description=AI intern, Python, n8n" -F "resume=@resume.pdf"
```

## Tests
```bash
pytest -q
```

## Docker
```bash
docker build -t ai-hiring . && docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... ai-hiring
```

## Deploy (free tier)
Push to GitHub, create a Web Service on Render, runtime Docker, add `ANTHROPIC_API_KEY` (and optionally
`APP_API_KEY`) as environment variables. Add the live URL to your resume.

## n8n workflow
Import `n8n/resume_screening_workflow.json`, set env var `ANTHROPIC_API_KEY`, connect Google Sheets
credentials, replace `YOUR_SHEET_ID`, then POST JSON `{candidate_email, resume_text, job_description}` to the webhook.

## Candidate email automation
Drafts shortlist / on-hold / rejection emails with Claude from a CSV of screening results. Dry run by default.
```bash
python -m app.email_drafter --input candidates.sample.csv --job-title "AI Intern" --company Virtuous
# add --send (and set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD) to actually send
```

## Design notes
- Resume and JD text are wrapped in tags and the model is told to treat them as data (prompt-injection hardening).
- Output is validated with pydantic; malformed model output returns HTTP 422, never a crash.
- Upload size limit, optional API-key auth, health endpoint, retries on the n8n API call.
- Screening is decision support only; a human should make final hiring decisions.
