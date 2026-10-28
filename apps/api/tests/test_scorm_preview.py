"""SCORM preview: the outline comes from the package's own manifest, files are served
from the zip only, preview links can never act as logins (or the reverse), and every
page runs sandboxed with the preview run-time in front of the package's scripts."""
import zipfile

import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.auth.security import create_access_token, decode_token
from app.core.export import scorm_preview as preview
from app.core.export.course import ExportCourse, ExportLesson
from app.core.export.scorm_builder import build_scorm
from app.routers.scorm_preview import package_file

PACKAGE = "artifacts/p1/20261028-000000/course_scorm12.zip"
QUESTION = {"stem": "When?", "options": ["Within 1 hour", "Tomorrow"], "answer_index": 0, "explanation": "Report quickly."}


def _course() -> ExportCourse:
    slides = [{"id": "s1", "layout": "bullets", "title": "Report", "bullets": ["Report within 1 hour"], "table": None, "notes": ""}]
    return ExportCourse(
        id="c1", title="Security basics", summary="", objectives=[],
        lessons=[
            ExportLesson(module_title="Accounts", title="Passwords", estimated_minutes=10, slides=slides, questions=[QUESTION]),
            ExportLesson(module_title="Accounts", title="MFA", estimated_minutes=5, slides=slides),
            ExportLesson(module_title="Incidents", title="Reporting", estimated_minutes=10, slides=slides, questions=[QUESTION]),
        ],
    )


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    path = tmp_path / PACKAGE
    path.parent.mkdir(parents=True)
    path.write_bytes(build_scorm(_course()))
    return path


def test_outline_is_read_from_the_built_manifest(package):
    with zipfile.ZipFile(package) as z:
        outline = preview.parse_manifest(z.read("imsmanifest.xml"))
    assert outline["title"] == "Security basics"
    modules = outline["items"]
    assert [m["title"] for m in modules] == ["Accounts", "Incidents"] and all(m["href"] is None for m in modules)
    lessons = [lesson for m in modules for lesson in m["children"]]
    assert [(lesson["title"], lesson["href"], lesson["mastery_score"]) for lesson in lessons] == [
        ("Passwords", "lessons/lesson_01.html", 70.0),
        ("MFA", "lessons/lesson_02.html", None),  # no quiz, so no mastery score
        ("Reporting", "lessons/lesson_03.html", 70.0),
    ]


def test_manifest_launch_details_and_refusals():
    manifest = b"""<?xml version="1.0"?>
    <manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
      <organizations default="b">
        <organization identifier="a"><title>Not this one</title></organization>
        <organization identifier="b"><title>Chosen</title>
          <item identifier="i1" identifierref="r1" parameters="?page=2"><title>One</title><adlcp:datafromlms>mode=quiz</adlcp:datafromlms></item>
          <item identifier="i2" identifierref="r1" isvisible="false"><title>Hidden</title></item>
        </organization>
      </organizations>
      <resources xml:base="content/"><resource identifier="r1" href="index.html?x=1" adlcp:scormtype="sco"/></resources>
    </manifest>"""
    outline = preview.parse_manifest(manifest)
    assert outline["title"] == "Chosen"
    assert outline["items"] == [{"id": "i1", "title": "One", "href": "content/index.html?x=1&page=2", "mastery_score": None, "launch_data": "mode=quiz", "children": []}]
    with pytest.raises(ValueError, match="unsupported"):
        preview.parse_manifest(b'<!DOCTYPE m [<!ENTITY a "aaaa">]><manifest/>')
    with pytest.raises(ValueError, match="no organization"):
        preview.parse_manifest(b"<manifest><organizations/></manifest>")


def test_preview_links_and_logins_are_not_interchangeable():
    token, _ = preview.create_token(user_id="u1", asset_id="a1", package=PACKAGE)
    claims = preview.read_token(token)
    assert claims and (claims["sub"], claims["asset"], claims["pkg"]) == ("u1", "a1", PACKAGE)
    assert decode_token(token) is None  # a leaked preview link cannot call the API
    assert preview.read_token(create_access_token("u1", "admin")) is None  # a login cannot open a package
    assert preview.read_token(token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]) is None


def test_expired_preview_link_is_refused(monkeypatch):
    monkeypatch.setattr(preview, "TOKEN_MINUTES", -1)
    token, _ = preview.create_token(user_id="u1", asset_id="a1", package=PACKAGE)
    assert preview.read_token(token) is None


@pytest.mark.parametrize("path", ["", "../secrets.zip", "/etc/passwd", "lessons/../../x", "lessons\\lesson_01.html", "a\x00b"])
def test_requests_cannot_leave_the_package(path):
    assert preview.member_name(path) is None


def test_member_names_are_normalised():
    assert preview.member_name("lessons/./lesson_01.html") == "lessons/lesson_01.html"


def test_runtime_runs_before_the_package_scripts():
    page = b'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><script src="../shared/scorm.js"></script></head><body></body></html>'
    out = preview.with_runtime(page)
    assert out.index(b"window.API") < out.index(b"../shared/scorm.js")
    assert preview.with_runtime(b"<!doctype html><p>no head</p>").startswith(b"<!doctype html><script>")
    assert preview.with_runtime(b"<p>bare</p>").startswith(b"<script>")
    assert "</script" not in preview.RUNTIME_JS.lower()


def test_package_pages_are_served_sandboxed_with_the_runtime(package):
    token, _ = preview.create_token(user_id="u1", asset_id="a1", package=PACKAGE)
    page = package_file(token, "lessons/lesson_01.html")
    assert page.status_code == 200 and page.media_type.startswith("text/html")
    body = page.body.decode()
    assert body.index("window.API") < body.index("../shared/scorm.js")
    csp = page.headers["content-security-policy"]
    assert "sandbox allow-scripts allow-forms" in csp and "connect-src 'none'" in csp
    assert "allow-same-origin" not in csp and all(origin in csp for origin in settings.cors_origin_list)
    assert page.headers["referrer-policy"] == "no-referrer"

    script = package_file(token, "shared/scorm.js")
    assert script.media_type.startswith("text/javascript") and b"window.API" not in script.body  # only pages get the runtime


@pytest.mark.parametrize(("path", "status"), [("../course_scorm12.zip", 404), ("lessons/missing.html", 404), ("lessons/", 404), ("imsmanifest.xml.bak", 404)])
def test_package_file_errors(package, path, status):
    token, _ = preview.create_token(user_id="u1", asset_id="a1", package=PACKAGE)
    with pytest.raises(HTTPException) as err:
        package_file(token, path)
    assert err.value.status_code == status


def test_bad_or_orphaned_links(package):
    with pytest.raises(HTTPException) as err:
        package_file("not-a-token", "lessons/lesson_01.html")
    assert err.value.status_code == 401
    token, _ = preview.create_token(user_id="u1", asset_id="a1", package="artifacts/p1/gone/course_scorm12.zip")
    with pytest.raises(HTTPException) as err:
        package_file(token, "lessons/lesson_01.html")
    assert err.value.status_code == 410


def test_open_session_returns_outline_and_grant(package):
    session = preview.open_session(PACKAGE, user_id="u1", asset_id="a1")
    assert session["title"] == "Security basics" and len(session["items"]) == 2
    token = session["base_path"].removeprefix("/scorm-preview/").rstrip("/")
    assert preview.read_token(token)["pkg"] == PACKAGE
    with pytest.raises(FileNotFoundError):
        preview.open_session("artifacts/none.zip", user_id="u1", asset_id="a1")
