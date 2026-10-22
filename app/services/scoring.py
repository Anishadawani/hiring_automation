"""Explainable, rules-based match scoring. No AI is involved in this score.

Method (also served to the UI at GET /api/recruiter/scoring-method):

  score = 100 x  sum(weight_i x ratio_i)  /  sum(weight_i)      over the components that apply

  required_skills   weight 0.60  ratio = required skills found / required skills listed
  preferred_skills  weight 0.15  ratio = preferred skills found / preferred skills listed
  experience        weight 0.25  ratio = min(1, years of experience / minimum years)

A component is skipped (and the remaining weights renormalised) when the job does not
define it, e.g. no preferred skills listed.

A skill counts as found when:
  - it appears as a whole word/term in the resume text (evidence = the surrounding text), or
  - the candidate listed it in their own profile (evidence is flagged as self-declared).

Inputs are limited to skills, resume text and employment dates. The score never uses
name, gender, age, photo, nationality, or any other protected characteristic.
"""
import re
from dataclasses import dataclass
from datetime import date

WEIGHTS = {"required_skills": 0.60, "preferred_skills": 0.15, "experience": 0.25}
SNIPPET_RADIUS = 60

METHODOLOGY = {
    "formula": "score = 100 x sum(weight x ratio) / sum(weights of components that apply)",
    "components": {
        "required_skills": "Weight 60%. Share of the job's required skills found in the resume or profile.",
        "preferred_skills": "Weight 15%. Share of preferred skills found. Skipped if the job lists none.",
        "experience": "Weight 25%. Years of experience (from profile dates, overlaps merged) divided by the "
        "job's minimum, capped at 100%. Skipped if the job sets no minimum.",
    },
    "skill_matching": "Literal whole-term matching, case-insensitive. No synonyms: 'Postgres' does not "
    "match 'PostgreSQL'. Skills found only in the candidate's own profile are labelled self-declared.",
    "limits": [
        "Advisory only. It never changes a candidate's stage; a recruiter makes every decision.",
        "A low score can mean the resume uses different wording, not that the skill is missing.",
        "Years of experience can correlate with age; recruiters should treat that component with care.",
    ],
}


@dataclass
class ScoreResult:
    score: float
    breakdown: dict
    matched_skills: list[str]
    missing_skills: list[str]
    evidence: list[dict]


def _pattern(skill: str) -> re.Pattern:
    # Letters/digits/+/# on either side mean it is part of a longer word (Java vs JavaScript).
    return re.compile(
        r"(?<![A-Za-z0-9+#])" + re.escape(skill.strip()) + r"(?![A-Za-z0-9+#])", re.IGNORECASE
    )


def find_skill(skill: str, resume_text: str, profile_skills: list[str]) -> dict | None:
    match = _pattern(skill).search(resume_text or "")
    if match:
        start = max(0, match.start() - SNIPPET_RADIUS)
        end = min(len(resume_text), match.end() + SNIPPET_RADIUS)
        return {"skill": skill, "source": "resume", "snippet": " ".join(resume_text[start:end].split())}
    if any(s.casefold() == skill.casefold() for s in profile_skills):
        return {"skill": skill, "source": "profile (self-declared)", "snippet": None}
    return None


def total_years_experience(experience: list[dict], today: date | None = None) -> float:
    """Sum of employment time with overlapping jobs merged, in years (1 decimal)."""
    today = today or date.today()
    spans: list[tuple[date, date]] = []
    for item in experience or []:
        try:
            start = date.fromisoformat(str(item["start_date"]))
            end = date.fromisoformat(str(item["end_date"])) if item.get("end_date") else today
        except (KeyError, ValueError):
            continue
        end = min(end, today)
        if start <= end:
            spans.append((start, end))
    spans.sort()
    merged: list[list[date]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    days = sum((end - start).days for start, end in merged)
    return round(days / 365.25, 1)


def score_application(
    required_skills: list[str],
    preferred_skills: list[str],
    min_years_experience: int,
    resume_text: str,
    profile_skills: list[str],
    experience: list[dict],
    today: date | None = None,
) -> ScoreResult:
    if not required_skills:
        raise ValueError("A job needs at least one required skill to be scored.")

    evidence: list[dict] = []
    components: dict[str, dict] = {}

    def skill_component(name: str, skills: list[str]) -> tuple[list[str], list[str]]:
        found, missing = [], []
        for skill in skills:
            hit = find_skill(skill, resume_text, profile_skills)
            if hit:
                found.append(skill)
                evidence.append({**hit, "kind": name})
            else:
                missing.append(skill)
        ratio = len(found) / len(skills)
        components[name] = {
            "weight": WEIGHTS[name],
            "ratio": round(ratio, 3),
            "detail": f"{len(found)} of {len(skills)} found",
        }
        return found, missing

    found_req, missing_req = skill_component("required_skills", required_skills)
    found_pref: list[str] = []
    missing_pref: list[str] = []
    if preferred_skills:
        found_pref, missing_pref = skill_component("preferred_skills", preferred_skills)

    years = total_years_experience(experience, today)
    if min_years_experience > 0:
        ratio = min(1.0, years / min_years_experience)
        components["experience"] = {
            "weight": WEIGHTS["experience"],
            "ratio": round(ratio, 3),
            "detail": f"{years} years of experience vs {min_years_experience} required",
        }

    total_weight = sum(c["weight"] for c in components.values())
    for c in components.values():
        c["points"] = round(100 * c["weight"] * c["ratio"] / total_weight, 1)
    score = round(sum(c["weight"] * c["ratio"] for c in components.values()) / total_weight * 100, 1)

    return ScoreResult(
        score=score,
        breakdown={
            "components": components,
            "years_of_experience": years,
            "missing_preferred": missing_pref,
            "formula": METHODOLOGY["formula"],
        },
        matched_skills=found_req + found_pref,
        missing_skills=missing_req,
        evidence=evidence,
    )