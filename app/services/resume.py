"""Resume ingestion: validate an upload, extract its text, store the file safely."""
import re
import uuid
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from app.config import get_settings

MAX_PAGES = 30
MAX_TEXT_CHARS = 20_000  # keeps later AI prompts bounded
ALLOWED_EXTENSIONS = {".pdf", ".txt"}


class ResumeError(Exception):
    """A problem with the uploaded resume that is safe to show to the user."""


def safe_display_name(filename: str | None) -> str:
    """Strip directories and unusual characters from a user-supplied filename."""
    name = Path(filename or "resume").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return (name or "resume")[:120]


def extract_text(filename: str | None, data: bytes) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ResumeError("Only PDF or plain-text (.txt) resumes are supported.")

    if ext == ".pdf":
        # Check the file's real signature, not just its name.
        if not data.startswith(b"%PDF-"):
            raise ResumeError("This file is not a valid PDF.")
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ResumeError("Password-protected PDFs are not supported.")
            if len(reader.pages) > MAX_PAGES:
                raise ResumeError(f"Resume has more than {MAX_PAGES} pages.")
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except ResumeError:
            raise
        except Exception as exc:  # corrupt PDF
            raise ResumeError("Could not read this PDF. The file may be corrupt.") from exc
    else:
        text = data.decode("utf-8", errors="ignore")

    text = text.replace("\x00", "").strip()
    if not text:
        raise ResumeError(
            "No readable text found. Scanned or image-only PDFs are not supported (no OCR)."
        )
    return text[:MAX_TEXT_CHARS]


def _root() -> Path:
    return Path(get_settings().upload_dir).resolve()


def store_resume(user_id: int, filename: str | None, data: bytes) -> str:
    """Save the file under a random name; returns a key relative to the upload root."""
    folder = _root() / "resumes" / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "").suffix.lower()
    path = folder / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return str(path.relative_to(_root()))


def resolve_resume_path(key: str) -> Path:
    """Turn a stored key into a path, refusing anything outside the upload folder."""
    root = _root()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ResumeError("Invalid file location.")
    return path


def delete_resume_file(key: str | None) -> None:
    if not key:
        return
    try:
        resolve_resume_path(key).unlink(missing_ok=True)
    except (ResumeError, OSError):
        pass