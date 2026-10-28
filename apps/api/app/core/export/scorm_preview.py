"""In-app preview of an exported SCORM 1.2 package, served exactly as it was built.

The web player takes the course outline from the package's own imsmanifest.xml and
loads each SCO from ``/scorm-preview/<token>/<path>``, read straight from the zip. The
token is a short-lived grant for one package, signed with a key derived from SECRET_KEY
but distinct from the login-token key: a preview link travels in URLs and access logs,
so it must never authenticate an API call, and a login token cannot open a preview.

Every SCO page gets the preview run-time (scorm_runtime.js) injected at the top of its
<head>, so the package's unmodified scorm.js finds ``window.API`` as it would in an LMS
frame. Pages are served under a sandbox CSP: they run in an opaque origin, cannot read
the app's session or storage, cannot make network requests, and report to the player
only by postMessage.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from jose import JWTError, jwt

from app.config import settings

SCOPE = "scorm_preview"
TOKEN_MINUTES = 120
MAX_MANIFEST_BYTES = 1_000_000
MAX_MEMBER_BYTES = 50_000_000
RUNTIME_JS = Path(__file__).with_name("scorm_runtime.js").read_text(encoding="utf-8")

_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_HEAD = re.compile(rb"<head\b[^>]*>", re.IGNORECASE)
_DOCTYPE = re.compile(rb"\s*<!doctype[^>]*>", re.IGNORECASE)
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".xml": "application/xml", ".txt": "text/plain; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".mp3": "audio/mpeg", ".mp4": "video/mp4", ".webm": "video/webm",
    ".vtt": "text/vtt",
}


def _key() -> str:
    return f"{settings.secret_key}:{SCOPE}"


def create_token(*, user_id: str, asset_id: str, package: str) -> tuple[str, datetime]:
    """A preview grant for one package; ``package`` is its path relative to DATA_DIR."""
    expires = datetime.now(UTC) + timedelta(minutes=TOKEN_MINUTES)
    claims = {"sub": user_id, "scope": SCOPE, "asset": asset_id, "pkg": package, "exp": expires}
    return jwt.encode(claims, _key(), algorithm=settings.jwt_algorithm), expires


def read_token(token: str) -> dict | None:
    try:
        claims = jwt.decode(token, _key(), algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return claims if claims.get("scope") == SCOPE and claims.get("pkg") else None


def package_path(rel: str) -> Path | None:
    root = settings.data_dir.resolve()
    path = (root / rel).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def member_name(path: str) -> str | None:
    """The zip member a request names, or None for anything that could leave the package."""
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return None
    parts = PurePosixPath(path).parts
    return None if ".." in parts else "/".join(parts)


def read_member(package: Path, name: str) -> bytes | None:
    with zipfile.ZipFile(package) as z:
        try:
            info = z.getinfo(name)
        except KeyError:
            return None
        if info.is_dir() or info.file_size > MAX_MEMBER_BYTES:
            return None
        return z.read(info)


def content_type(name: str) -> str | None:
    return CONTENT_TYPES.get(PurePosixPath(name).suffix.lower())


def with_runtime(page: bytes) -> bytes:
    """The SCO page with the preview run-time first in <head>, before any package script."""
    tag = b"<script>" + RUNTIME_JS.encode("utf-8") + b"</script>"
    at = _HEAD.search(page) or _DOCTYPE.match(page)
    return page[: at.end()] + tag + page[at.end() :] if at else tag + page


def response_headers() -> dict[str, str]:
    ancestors = " ".join(settings.cors_origin_list) or "'none'"
    return {
        "Content-Security-Policy": "sandbox allow-scripts allow-forms; connect-src 'none'; form-action 'none'; base-uri 'none'; "
        f"object-src 'none'; frame-ancestors {ancestors}",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name] if el is not None else []


def _text(el: ET.Element, name: str) -> str:
    found = _children(el, name)
    return (found[0].text or "").strip() if found else ""


def _launch_href(href: str, parameters: str) -> str:
    """Resource href plus the item's ``parameters`` (SCORM 1.2 CAM 3.4.1.10)."""
    parameters = parameters.strip()
    if not parameters:
        return href
    if parameters[0] == "#":
        return href + parameters
    return href + ("&" if "?" in href else "?") + parameters.lstrip("?&")


def parse_manifest(data: bytes) -> dict:
    """Course title and organization tree of a SCORM 1.2 manifest.

    Namespace prefixes are ignored so manifests written against other IMS CP versions
    still read. Each item: id, title, launch href (None for a grouping), mastery score,
    launch data and visible children. DTDs are refused: this parser must not expand
    entities.
    """
    if len(data) > MAX_MANIFEST_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("The package manifest uses an unsupported XML feature.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"The package manifest is not valid XML: {exc}") from exc
    resources = next(iter(_children(root, "resources")), None)
    base = (root.get(_XML_BASE) or "") + (resources.get(_XML_BASE) or "" if resources is not None else "")
    hrefs = {r.get("identifier"): base + (r.get(_XML_BASE) or "") + r.get("href") for r in _children(resources, "resource") if r.get("href")}

    organizations = next(iter(_children(root, "organizations")), None)
    orgs = _children(organizations, "organization")
    if not orgs:
        raise ValueError("The package manifest has no organization.")
    default = organizations.get("default") if organizations is not None else None
    org = next((o for o in orgs if o.get("identifier") == default), orgs[0])

    def item(el: ET.Element) -> dict:
        ref = el.get("identifierref")
        mastery = _text(el, "masteryscore")
        try:
            mastery_score = float(mastery) if mastery else None
        except ValueError:
            mastery_score = None
        return {
            "id": el.get("identifier") or "",
            "title": _text(el, "title") or el.get("identifier") or "Untitled",
            "href": _launch_href(hrefs[ref], el.get("parameters") or "") if ref in hrefs else None,
            "mastery_score": mastery_score,
            "launch_data": _text(el, "datafromlms"),
            "children": [item(c) for c in _children(el, "item") if c.get("isvisible", "true") != "false"],
        }

    return {"title": _text(org, "title") or "Untitled course", "items": [item(c) for c in _children(org, "item") if c.get("isvisible", "true") != "false"]}


def open_session(package_rel: str, *, user_id: str, asset_id: str) -> dict:
    """Outline and preview grant for one exported package."""
    path = package_path(package_rel)
    if path is None:
        raise FileNotFoundError(package_rel)
    manifest = read_member(path, "imsmanifest.xml")
    if manifest is None:
        raise ValueError("This export has no imsmanifest.xml, so it is not a SCORM package.")
    outline = parse_manifest(manifest)
    token, expires = create_token(user_id=user_id, asset_id=asset_id, package=package_rel)
    return {**outline, "base_path": f"/scorm-preview/{token}/", "expires_at": expires}
