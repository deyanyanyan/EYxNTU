"""Viewable renditions of uploaded sources, for the in-app source viewer.

PDF, Markdown and text sources are shown as uploaded. Word and PowerPoint sources are
rendered to PDF once, during ingestion, by headless LibreOffice (installed in the worker
image only), so the browser's own PDF viewer shows them with their original layout. The
rendition sits beside the upload as ``<upload>.pdf``.

A failed or missing rendition never fails ingestion: the source still feeds course
generation, and the viewer offers the original file instead. LibreOffice runs with its
default macro security, so document macros do not execute; it may still try to fetch
resources a document links to, which the air-gapped deployment blocks.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

RENDERED = {".docx", ".pptx"}  # converted to PDF for viewing
TEXT = {".md", ".txt"}
TIMEOUT_SECONDS = 180


def rendition_path(storage_path: str) -> str:
    """Where a source's PDF rendition lives, relative to DATA_DIR."""
    return f"{storage_path}.pdf"


def viewer_kind(storage_path: str) -> str | None:
    """How the viewer shows a source: "pdf", "text", or None when nothing viewable exists yet."""
    ext = Path(storage_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT:
        return "text"
    if ext in RENDERED and (settings.data_dir / rendition_path(storage_path)).is_file():
        return "pdf"
    return None


def render_pdf(source: Path, out: Path) -> None:
    """Convert a Word or PowerPoint file to PDF with headless LibreOffice, replacing ``out``."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice is not installed in this image")
    with tempfile.TemporaryDirectory(prefix="rendition-") as tmp:
        work = Path(tmp)
        # A private profile per run: concurrent conversions sharing one profile lock each other out.
        cmd = [
            soffice, f"-env:UserInstallation={(work / 'profile').as_uri()}", "--headless", "--norestore", "--nolockcheck",
            "--convert-to", "pdf", "--outdir", str(work), str(source),
        ]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
        produced = work / f"{source.stem}.pdf"
        if done.returncode != 0 or not produced.is_file():
            raise RuntimeError(f"LibreOffice could not convert {source.name}: {(done.stderr or done.stdout).strip()[:300]}")
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + ".part")
        shutil.copyfile(produced, partial)  # copy, then rename: the viewer never sees half a file
        partial.replace(out)
