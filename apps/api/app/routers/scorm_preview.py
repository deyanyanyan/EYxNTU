"""Package files for the in-app SCORM preview (app/core/export/scorm_preview.py).

No login: the path's token is the grant, scoped to one package and short-lived. Relative
links inside the package keep the token, because it is a path segment, not a query.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.export import scorm_preview as preview

router = APIRouter(prefix="/scorm-preview", tags=["preview"])


@router.get("/{token}/{path:path}")
def package_file(token: str, path: str) -> Response:
    claims = preview.read_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="This preview link has expired. Reopen the preview.")
    package = preview.package_path(claims["pkg"])
    if package is None:
        raise HTTPException(status_code=410, detail="The exported package is no longer on disk. Export again.")
    name = preview.member_name(path)
    media_type = preview.content_type(name) if name else None
    data = preview.read_member(package, name) if media_type else None
    if data is None:
        raise HTTPException(status_code=404, detail="No such file in this package")
    if media_type.startswith("text/html"):
        data = preview.with_runtime(data)
    return Response(content=data, media_type=media_type, headers=preview.response_headers())
