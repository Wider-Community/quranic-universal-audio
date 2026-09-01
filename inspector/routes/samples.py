"""Maintainer sample endpoints (``samples.manage``).

- ``GET    /api/samples``             list every sample (shared across maintainers).
- ``POST   /api/samples``             multipart upload: ``name``, ``audio``, ``source``.
- ``PATCH  /api/samples/<id>``        rename (owner of the sample, or owner role).
- ``DELETE /api/samples/<id>``        remove folder + row (same rule).
- ``GET    /api/samples/<id>/export`` download the edited segments in the uploaded
  schema. A GET with a side effect (stamps ``last_export_at``) so the browser can
  save it as a plain download.

Segment reads/edits go through the ordinary ``/api/seg/*`` routes on the slug
``sample--<id>``; ``require_edit_lock`` carries the sample gate.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from config import AUDIO_MIME_TYPES
from qua_shared.schemas import SampleRenameRequest, SampleRow, SamplesListResponse
from services import samples as samples_service
from utils.decorators import require_capability, require_same_origin

samples_bp = Blueprint("samples", __name__, url_prefix="/api/samples")


def _row(view: dict) -> dict:
    return SampleRow.model_validate(view).model_dump(mode="json")


def _list_body(views: list[dict]) -> dict:
    rows = [SampleRow.model_validate(v) for v in views]
    return SamplesListResponse(samples=rows).model_dump(mode="json")


def _handle(exc: Exception):
    if isinstance(exc, samples_service.SampleNotFound):
        return jsonify({"error": "sample not found"}), 404
    if isinstance(exc, samples_service.SampleForbidden):
        return jsonify({"error": "only the sample's owner can do that"}), 403
    if isinstance(exc, samples_service.SampleError):
        return jsonify({"error": str(exc)}), 400
    raise exc


@samples_bp.route("")
@require_capability("samples.manage")
def list_samples(user):
    return jsonify(_list_body(samples_service.list_samples(user)))


@samples_bp.route("", methods=["POST"])
@require_same_origin
@require_capability("samples.manage")
def create_sample(user):
    audio = request.files.get("audio")
    source = request.files.get("source")
    if audio is None or not audio.filename or source is None:
        return jsonify({"error": "audio and source files are required"}), 400
    ext = Path(audio.filename).suffix.lower()
    if ext not in AUDIO_MIME_TYPES:
        return jsonify({"error": f"unsupported audio type {ext or '(none)'}"}), 400
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / f"upload{ext}"
        audio.save(audio_path)
        try:
            view = samples_service.create_sample(
                user=user,
                name=request.form.get("name", ""),
                audio_path=audio_path,
                audio_filename=Path(audio.filename).name,
                json_bytes=source.read(),
            )
        except (samples_service.SampleError, samples_service.SampleNotFound) as exc:
            return _handle(exc)
    return jsonify(_row(view)), 201


@samples_bp.route("/<sample_id>", methods=["PATCH"])
@require_same_origin
@require_capability("samples.manage")
def rename_sample(user, sample_id):
    try:
        req = SampleRenameRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid name", "details": exc.errors()}), 400
    try:
        view = samples_service.rename_sample(sample_id, req.name, user=user)
    except (
        samples_service.SampleError,
        samples_service.SampleNotFound,
        samples_service.SampleForbidden,
    ) as exc:
        return _handle(exc)
    return jsonify(_row(view))


@samples_bp.route("/<sample_id>", methods=["DELETE"])
@require_same_origin
@require_capability("samples.manage")
def delete_sample(user, sample_id):
    try:
        samples_service.delete_sample(sample_id, user=user)
    except (samples_service.SampleNotFound, samples_service.SampleForbidden) as exc:
        return _handle(exc)
    return ("", 204)


@samples_bp.route("/<sample_id>/export")
@require_capability("samples.manage")
def export_sample(user, sample_id):
    try:
        filename, body = samples_service.export_sample(sample_id, user=user)
    except samples_service.SampleNotFound as exc:
        return _handle(exc)
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
