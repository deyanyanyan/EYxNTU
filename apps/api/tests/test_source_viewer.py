"""Source viewer: every upload type maps to one way of showing it, Word and PowerPoint are
shown through their PDF rendition, served types come from the extension (never from the
upload), and nothing outside DATA_DIR can be read."""
import shutil
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.rag import rendition
from app.models.project import Project
from app.models.source import Source
from app.routers.sources import source_original, source_view
from app.schemas.project import SourceOut

ADMIN = SimpleNamespace(id="u1", role="admin")


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "uploads" / "p1").mkdir(parents=True)
    return tmp_path


def _source(rel: str, **kw) -> SimpleNamespace:
    return SimpleNamespace(id="s1", project_id="p1", filename=rel.rsplit("/", 1)[-1], storage_path=rel, **kw)


class _FakeDB:
    def __init__(self, source):
        self.source = source

    def get(self, model, key):
        if model is Project:
            return SimpleNamespace(id=key, owner_id="u1")
        return self.source if model is Source and key == self.source.id else None


def test_rendition_sits_beside_the_upload():
    assert rendition.rendition_path("uploads/p1/ab_deck.pptx") == "uploads/p1/ab_deck.pptx.pdf"


def test_viewer_kind_by_type(data):
    assert rendition.viewer_kind("uploads/p1/a.pdf") == "pdf"
    assert rendition.viewer_kind("uploads/p1/a.MD") == "text" and rendition.viewer_kind("uploads/p1/a.txt") == "text"
    assert rendition.viewer_kind("uploads/p1/a.docx") is None  # not rendered yet
    (data / "uploads/p1/a.docx.pdf").write_bytes(b"%PDF-1.7")
    assert rendition.viewer_kind("uploads/p1/a.docx") == "pdf"
    assert rendition.viewer_kind("uploads/p1/a.xlsx") is None


def test_source_out_reports_the_viewer_but_not_the_storage_path(data):
    row = _source("uploads/p1/a.pdf", content_type="application/pdf", size_bytes=10, status="ready", error=None, page_count=1, chunk_count=2,
                  created_at=datetime.now(UTC))
    out = SourceOut.model_validate(row).model_dump()
    assert out["viewer"] == "pdf" and "storage_path" not in out


def test_view_serves_types_by_extension(data):
    (data / "uploads/p1/notes.md").write_text("# Heading\n<script>alert(1)</script>", encoding="utf-8")
    text = source_view("p1", "s1", actor=ADMIN, db=_FakeDB(_source("uploads/p1/notes.md")))
    assert text.media_type.startswith("text/plain") and text.headers["x-content-type-options"] == "nosniff"

    (data / "uploads/p1/deck.pptx").write_bytes(b"PK")
    with pytest.raises(HTTPException) as err:
        source_view("p1", "s1", actor=ADMIN, db=_FakeDB(_source("uploads/p1/deck.pptx")))
    assert err.value.status_code == 404  # no rendition yet: the viewer offers the original instead
    (data / "uploads/p1/deck.pptx.pdf").write_bytes(b"%PDF-1.7")
    pdf = source_view("p1", "s1", actor=ADMIN, db=_FakeDB(_source("uploads/p1/deck.pptx")))
    assert pdf.media_type == "application/pdf" and str(pdf.path).endswith("deck.pptx.pdf")

    original = source_original("p1", "s1", actor=ADMIN, db=_FakeDB(_source("uploads/p1/deck.pptx")))
    assert original.media_type == "application/octet-stream" and str(original.path).endswith("deck.pptx")


def test_paths_outside_data_dir_are_refused(data):
    outside = data.parent / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(HTTPException) as err:
        source_view("p1", "s1", actor=ADMIN, db=_FakeDB(_source("../secret.txt")))
    assert err.value.status_code == 410


def test_sources_of_other_projects_are_not_found(data):
    other = _source("uploads/p1/a.pdf")
    other.project_id = "p2"
    with pytest.raises(HTTPException) as err:
        source_view("p1", "s1", actor=ADMIN, db=_FakeDB(other))
    assert err.value.status_code == 404


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice is installed in the worker image only")
def test_libreoffice_renders_word_to_pdf(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("Reporting security incidents", level=1)
    doc.add_paragraph("Report every suspected incident within 1 hour.")
    source = tmp_path / "ab_handbook.docx"
    doc.save(source)
    out = tmp_path / "rendered" / "ab_handbook.docx.pdf"
    rendition.render_pdf(source, out)
    assert out.read_bytes().startswith(b"%PDF") and not out.with_name(out.name + ".part").exists()
