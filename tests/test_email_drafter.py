import csv
import json
from types import SimpleNamespace

import pytest

from app import email_drafter as ed

GOOD = json.dumps({"subject": "Interview invitation", "body": "Hi Asha, please share your availability."})


def fake_client(text=GOOD):
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)])))


CAND = {"name": "Asha", "email": "asha@example.com", "recommendation": "shortlist", "summary": "Strong Python"}


def test_draft_email_ok():
    assert ed.draft_email(CAND, "AI Intern", "Virtuous", client=fake_client())["subject"] == "Interview invitation"


def test_draft_email_bad_recommendation():
    with pytest.raises(ed.DraftError):
        ed.draft_email(dict(CAND, recommendation="hire"), "x", "y", client=fake_client())


def test_draft_email_bad_json():
    with pytest.raises(ed.DraftError):
        ed.draft_email(CAND, "x", "y", client=fake_client("not json"))


def test_read_candidates_requires_columns(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("name,email\nA,a@x.com\n")
    with pytest.raises(ed.DraftError):
        ed.read_candidates(str(p))


def test_dry_run_does_not_send(tmp_path):
    sent = []
    out = tmp_path / "d.csv"
    res = ed.process([CAND], "AI Intern", "Virtuous", str(out), send=False,
                     client=fake_client(), sender=lambda *a: sent.append(a))
    assert sent == [] and res[0]["status"] == "drafted"
    assert list(csv.DictReader(open(out)))[0]["subject"] == "Interview invitation"


def test_send_mode_calls_sender(tmp_path):
    sent = []
    res = ed.process([CAND], "AI Intern", "Virtuous", str(tmp_path / "d.csv"), send=True,
                     client=fake_client(), sender=lambda *a: sent.append(a))
    assert len(sent) == 1 and res[0]["status"] == "sent"


def test_batch_continues_after_error(tmp_path):
    bad = dict(CAND, name="Bad", recommendation="???")
    res = ed.process([bad, CAND], "AI Intern", "Virtuous", str(tmp_path / "d.csv"), client=fake_client())
    assert res[0]["status"].startswith("error") and res[1]["status"] == "drafted"
