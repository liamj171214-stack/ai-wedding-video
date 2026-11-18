#!/usr/bin/env python3
"""Validate project.yaml, shots.yaml, human review records, and optional media."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

SUPPORTED_SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RESOLUTION_RE = re.compile(r"^(\d+)x(\d+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

VALID_ASSET_KINDS = {"character", "set", "framing", "prop", "style", "audio"}
VALID_SHOT_KINDS = {"performance", "insert"}
VALID_SHOT_STATUSES = {"pending", "candidate", "approved"}
VALID_REVIEW_STATUSES = {"pending", "approved", "reshoot", "reselect"}

VIDEO_EXTENSIONS = {".mp4", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
INSERT_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

PLACEHOLDER_REVIEWERS = {
    "",
    "待填写",
    "待审",
    "tbd",
    "todo",
    "none",
    "null",
    "n/a",
    "unknown",
    "<human-name>",
}
AGENT_REVIEWER_TOKENS = {
    "agent",
    "bot",
    "ai",
    "claude",
    "codex",
    "gemini",
    "antigravity",
    "gpt",
    "chatgpt",
    "copilot",
    "github-actions",
    "llm",
}

REVIEW_TABLE_STATUS_MAP = {
    "approved": "approved",
    "通过": "approved",
    "reshoot": "reshoot",
    "补拍": "reshoot",
    "reselect": "reselect",
    "换候选": "reselect",
    "pending": "pending",
    "待审": "pending",
}

REQUIRED_PROJECT_KEYS = {"schema_version", "slug", "title", "fps", "resolution", "assets"}
REQUIRED_ASSET_KEYS = {"path", "kind", "version", "sha256"}
REQUIRED_SHOT_KEYS = {
    "id",
    "scene",
    "camera",
    "target_duration",
    "action",
    "dialogue",
    "refs",
    "kind",
    "status",
    "candidates",
    "selected",
}
OPTIONAL_SHOT_KEYS = {"sound", "listener", "note"}
REQUIRED_CANDIDATE_KEYS = {"id", "engine", "file", "sha256"}
OPTIONAL_CANDIDATE_KEYS = {"note"}
REQUIRED_DIALOGUE_KEYS = {"speaker", "at", "end", "text"}
ALLOWED_SELECTED_KEYS = {"candidate", "in", "out", "audio", "review", "note", "crop", "fit"}


@dataclass(frozen=True)
class ProbeInfo:
    """Media stream and duration metadata extracted via ffprobe."""

    duration: float | None
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    fps: float | None = None


@dataclass
class ValidationResult:
    """Structured result returned by validate_project."""

    project_dir: Path
    repo_root: Path
    project: dict[str, Any] = field(default_factory=dict)
    shots: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_real_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def infer_repo_root(project_dir: Path) -> Path:
    resolved = project_dir.resolve()
    if resolved.parent.name == "projects":
        return resolved.parent.parent
    for parent in resolved.parents:
        if (parent / ".git").exists():
            return parent
    return resolved.parent


def resolve_confined_path(base_dir: Path, raw_rel: str) -> Path | None:
    """Resolve raw_rel inside base_dir, returning None if absolute or escaping base_dir."""
    if not isinstance(raw_rel, str) or not raw_rel.strip():
        return None
    rel_path = Path(raw_rel)
    if rel_path.is_absolute():
        return None
    base_resolved = base_dir.resolve()
    candidate = (base_resolved / rel_path).resolve()
    if candidate == base_resolved:
        return None
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate


def _parse_rate(rate_str: str | None) -> float | None:
    if not rate_str or rate_str == "0/0":
        return None
    if "/" in rate_str:
        num_s, den_s = rate_str.split("/", 1)
        try:
            num, den = float(num_s), float(den_s)
        except ValueError:
            return None
        return num / den if den != 0 else None
    try:
        return float(rate_str)
    except ValueError:
        return None


def probe_media(path: Path) -> ProbeInfo:
    """Inspect a local media file with ffprobe."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"ffprobe failed on {path}: {detail}")

    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}

    has_video = False
    has_audio = False
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    fps: float | None = None
    stream_durations: list[float] = []

    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "video" and not has_video:
            has_video = True
            width = stream.get("width")
            height = stream.get("height")
            video_codec = stream.get("codec_name")
            fps = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(
                stream.get("r_frame_rate")
            )
        elif codec_type == "audio" and not has_audio:
            has_audio = True
            audio_codec = stream.get("codec_name")

        dur_raw = stream.get("duration")
        if dur_raw is not None:
            try:
                dur_val = float(dur_raw)
                if math.isfinite(dur_val) and dur_val > 0:
                    stream_durations.append(dur_val)
            except (TypeError, ValueError):
                pass

    duration: float | None = None
    fmt_dur = fmt.get("duration")
    if fmt_dur is not None:
        try:
            val = float(fmt_dur)
            if math.isfinite(val) and val > 0:
                duration = val
        except (TypeError, ValueError):
            pass
    if duration is None and stream_durations:
        duration = max(stream_durations)

    return ProbeInfo(
        duration=duration,
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        video_codec=video_codec,
        audio_codec=audio_codec,
        fps=fps,
    )


def _is_valid_human_reviewer(value: Any) -> bool:
    if not is_non_empty_str(value):
        return False
    cleaned = value.strip()
    lowered = cleaned.lower()
    if lowered in PLACEHOLDER_REVIEWERS or cleaned in PLACEHOLDER_REVIEWERS:
        return False
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", lowered) if tok]
    if any(tok in AGENT_REVIEWER_TOKENS for tok in tokens):
        return False
    if lowered in AGENT_REVIEWER_TOKENS:
        return False
    if any(word in cleaned for word in ("智能体", "机器人", "自动代理")):
        return False
    return True


def _is_valid_review_date(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not is_non_empty_str(value):
        return False
    text = value.strip()
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        pass
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def _parse_review_table_rows(markdown_body: str) -> list[tuple[str, str, str]]:
    """Extract (shot_id, candidate, normalized_status_or_raw) rows from ## 逐镜结论."""
    rows: list[tuple[str, str, str]] = []
    in_section = False
    header_seen = False
    separator_seen = False

    for raw_line in markdown_body.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if in_section:
                break
            if line.startswith("## 逐镜结论"):
                in_section = True
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if not header_seen:
            header_seen = True
            continue
        if not separator_seen:
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                separator_seen = True
                continue
            separator_seen = True
        shot_cell = cells[0].strip("` ")
        cand_cell = cells[1].strip("` ")
        status_cell = cells[2].strip("` ") if len(cells) == 4 else cells[3].strip("` ")
        if not shot_cell or shot_cell == "待填写":
            continue
        if cand_cell == "待填写" and status_cell in {"待审", "pending", "待填写"}:
            continue
        rows.append((shot_cell, cand_cell, status_cell))
    return rows


@dataclass
class _ParsedReview:
    decisions: dict[str, dict[str, str]]
    valid: bool


def _load_and_validate_review(
    review_path: Path,
    rel_label: str,
    errors: list[str],
) -> _ParsedReview:
    if not review_path.is_file():
        errors.append(f"review file does not exist: {rel_label}")
        return _ParsedReview(decisions={}, valid=False)

    raw_text = review_path.read_text(encoding="utf-8")
    if not raw_text.startswith("---\n"):
        errors.append(f"{rel_label}: missing YAML frontmatter opening '---'")
        return _ParsedReview(decisions={}, valid=False)

    parts = raw_text.split("\n---\n", 1)
    if len(parts) != 2:
        errors.append(f"{rel_label}: missing YAML frontmatter closing '---'")
        return _ParsedReview(decisions={}, valid=False)

    fm_text = parts[0][4:]
    body_text = parts[1]
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        errors.append(f"{rel_label}: invalid YAML frontmatter: {exc}")
        return _ParsedReview(decisions={}, valid=False)

    if not isinstance(fm, dict):
        errors.append(f"{rel_label}: YAML frontmatter must be a mapping")
        return _ParsedReview(decisions={}, valid=False)

    ok = True
    if fm.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"{rel_label}: schema_version must be {SUPPORTED_SCHEMA_VERSION}, "
            f"got {fm.get('schema_version')!r}"
        )
        ok = False

    if not _is_valid_human_reviewer(fm.get("reviewer")):
        errors.append(
            f"{rel_label}: reviewer must be a non-empty human identifier "
            f"(got {fm.get('reviewer')!r})"
        )
        ok = False

    if not _is_valid_review_date(fm.get("reviewed_at")):
        errors.append(
            f"{rel_label}: reviewed_at must be a valid ISO 8601 date/datetime "
            f"(got {fm.get('reviewed_at')!r})"
        )
        ok = False

    raw_decisions = fm.get("decisions")
    decisions: dict[str, dict[str, str]] = {}
    if not isinstance(raw_decisions, dict) or not raw_decisions:
        errors.append(f"{rel_label}: decisions must be a non-empty mapping")
        ok = False
    else:
        for shot_key, entry in raw_decisions.items():
            shot_id = str(shot_key)
            if not isinstance(entry, dict):
                errors.append(f"{rel_label}: decisions[{shot_id!r}] must be a mapping")
                ok = False
                continue
            cand = entry.get("candidate")
            st = entry.get("status")
            if not is_non_empty_str(cand):
                errors.append(
                    f"{rel_label}: decisions[{shot_id!r}].candidate must be a non-empty string"
                )
                ok = False
            if st not in VALID_REVIEW_STATUSES:
                errors.append(
                    f"{rel_label}: decisions[{shot_id!r}].status must be one of "
                    f"{sorted(VALID_REVIEW_STATUSES)}, got {st!r}"
                )
                ok = False
            if is_non_empty_str(cand) and st in VALID_REVIEW_STATUSES:
                decisions[shot_id] = {"candidate": cand.strip(), "status": st}

    for row_shot, row_cand, row_status_raw in _parse_review_table_rows(body_text):
        mapped_status = REVIEW_TABLE_STATUS_MAP.get(row_status_raw.lower(), row_status_raw)
        mapped_status = REVIEW_TABLE_STATUS_MAP.get(row_status_raw, mapped_status)
        if mapped_status not in VALID_REVIEW_STATUSES:
            errors.append(
                f"{rel_label}: table row for shot {row_shot!r} has invalid status {row_status_raw!r}"
            )
            ok = False
            continue
        if row_shot not in decisions:
            errors.append(
                f"{rel_label}: table row for shot {row_shot!r} is missing from frontmatter decisions"
            )
            ok = False
            continue
        fm_entry = decisions[row_shot]
        if fm_entry["candidate"] != row_cand or fm_entry["status"] != mapped_status:
            errors.append(
                f"{rel_label}: table row for shot {row_shot!r} ({row_cand}, {mapped_status}) "
                f"disagrees with frontmatter ({fm_entry['candidate']}, {fm_entry['status']})"
            )
            ok = False

    return _ParsedReview(decisions=decisions, valid=ok)


def select_shot_range(shots: list[dict[str, Any]], shot_range: str | None) -> list[dict[str, Any]]:
    """Select an ordered slice of shots from shots.yaml by 'start-end' or single shot id."""
    if not shot_range:
        return list(shots)
    spec = shot_range.strip()
    index_by_id = {str(s["id"]): idx for idx, s in enumerate(shots)}
    if "-" in spec:
        start_id, end_id = spec.split("-", 1)
        start_id, end_id = start_id.strip(), end_id.strip()
        if start_id not in index_by_id:
            raise ValueError(f"Start shot {start_id!r} not found in shots.yaml")
        if end_id not in index_by_id:
            raise ValueError(f"End shot {end_id!r} not found in shots.yaml")
        start_idx = index_by_id[start_id]
        end_idx = index_by_id[end_id]
        if start_idx > end_idx:
            raise ValueError(
                f"Shot range {spec!r} is reversed ({start_id!r} appears after {end_id!r})"
            )
        return shots[start_idx : end_idx + 1]
    if spec not in index_by_id:
        raise ValueError(f"Shot {spec!r} not found in shots.yaml")
    return [shots[index_by_id[spec]]]


def _load_yaml_mapping(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing required manifest file: {label} ({path})")
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"{label}: invalid YAML syntax: {exc}")
        return None
    if not isinstance(loaded, dict):
        errors.append(f"{label}: top-level YAML document must be a mapping")
        return None
    return loaded


def validate_project(
    project_dir: Path | str,
    *,
    check_media: bool = False,
    media_shot_ids: set[str] | None = None,
    repo_root: Path | None = None,
) -> ValidationResult:
    """Validate a project's manifests, reviews, and (optionally) local candidate media."""
    proj_path = Path(project_dir).resolve()
    root_path = repo_root.resolve() if repo_root is not None else infer_repo_root(proj_path)
    result = ValidationResult(project_dir=proj_path, repo_root=root_path)
    errors = result.errors

    if not proj_path.is_dir():
        errors.append(f"project directory does not exist: {proj_path}")
        return result

    project_doc = _load_yaml_mapping(proj_path / "project.yaml", "project.yaml", errors)
    shots_doc = _load_yaml_mapping(proj_path / "shots.yaml", "shots.yaml", errors)
    if project_doc is None or shots_doc is None:
        return result

    result.project = project_doc

    # --- Validate project.yaml ---
    missing_proj = REQUIRED_PROJECT_KEYS - set(project_doc.keys())
    unknown_proj = set(project_doc.keys()) - REQUIRED_PROJECT_KEYS
    if missing_proj:
        errors.append(f"project.yaml: missing required fields: {sorted(missing_proj)}")
    if unknown_proj:
        errors.append(f"project.yaml: unknown fields: {sorted(unknown_proj)}")

    if project_doc.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"project.yaml: schema_version must be {SUPPORTED_SCHEMA_VERSION}, "
            f"got {project_doc.get('schema_version')!r}"
        )

    slug = project_doc.get("slug")
    if not is_non_empty_str(slug) or not SLUG_RE.fullmatch(slug):
        errors.append(f"project.yaml: invalid slug {slug!r}")
    elif slug != proj_path.name:
        errors.append(
            f"project.yaml: slug {slug!r} does not match directory name {proj_path.name!r}"
        )

    if not is_non_empty_str(project_doc.get("title")):
        errors.append("project.yaml: title must be a non-empty string")

    fps = project_doc.get("fps")
    if not is_strict_int(fps) or fps <= 0:
        errors.append(f"project.yaml: fps must be a positive integer, got {fps!r}")

    resolution = project_doc.get("resolution")
    if not isinstance(resolution, str) or not RESOLUTION_RE.fullmatch(resolution):
        errors.append(f"project.yaml: resolution must match '<W>x<H>', got {resolution!r}")
    else:
        res_match = RESOLUTION_RE.fullmatch(resolution)
        assert res_match is not None
        width, height = int(res_match.group(1)), int(res_match.group(2))
        if width <= 0 or height <= 0 or width % 2 != 0 or height % 2 != 0:
            errors.append(
                f"project.yaml: resolution dimensions must be positive even integers, got {resolution!r}"
            )

    assets_raw = project_doc.get("assets")
    valid_assets: dict[str, dict[str, Any]] = {}
    if not isinstance(assets_raw, dict) or not assets_raw:
        errors.append("project.yaml: assets must be a non-empty mapping")
    else:
        for asset_id, meta in assets_raw.items():
            if not is_non_empty_str(asset_id):
                errors.append(f"project.yaml: invalid asset key {asset_id!r}")
                continue
            if not isinstance(meta, dict):
                errors.append(f"project.yaml: assets.{asset_id} must be a mapping")
                continue
            missing_a = REQUIRED_ASSET_KEYS - set(meta.keys())
            unknown_a = set(meta.keys()) - REQUIRED_ASSET_KEYS
            if missing_a:
                errors.append(
                    f"project.yaml: assets.{asset_id} missing fields: {sorted(missing_a)}"
                )
            if unknown_a:
                errors.append(
                    f"project.yaml: assets.{asset_id} unknown fields: {sorted(unknown_a)}"
                )

            kind = meta.get("kind")
            if kind not in VALID_ASSET_KINDS:
                errors.append(
                    f"project.yaml: assets.{asset_id}.kind must be one of "
                    f"{sorted(VALID_ASSET_KINDS)}, got {kind!r}"
                )

            version = meta.get("version")
            if not is_strict_int(version) or version < 1:
                errors.append(
                    f"project.yaml: assets.{asset_id}.version must be an integer >= 1, "
                    f"got {version!r}"
                )

            expected_sha = meta.get("sha256")
            sha_valid = isinstance(expected_sha, str) and bool(SHA256_RE.fullmatch(expected_sha))
            if not sha_valid:
                errors.append(
                    f"project.yaml: assets.{asset_id}.sha256 must be a 64-char lowercase hex string"
                )

            raw_asset_path = meta.get("path")
            asset_path = resolve_confined_path(root_path, raw_asset_path)
            if asset_path is None:
                errors.append(
                    f"project.yaml: assets.{asset_id}.path must be a relative path inside repo root, "
                    f"got {raw_asset_path!r}"
                )
            elif not asset_path.is_file():
                errors.append(
                    f"project.yaml: assets.{asset_id} file does not exist: {raw_asset_path}"
                )
            elif sha_valid:
                actual_sha = sha256_file(asset_path)
                if actual_sha != expected_sha:
                    errors.append(
                        f"project.yaml: assets.{asset_id} sha256 mismatch for {raw_asset_path}: "
                        f"expected {expected_sha}, got {actual_sha}"
                    )

            valid_assets[asset_id] = meta

    # --- Validate shots.yaml ---
    allowed_shots_top = {"schema_version", "shots"}
    missing_shots_top = allowed_shots_top - set(shots_doc.keys())
    unknown_shots_top = set(shots_doc.keys()) - allowed_shots_top
    if missing_shots_top:
        errors.append(f"shots.yaml: missing required fields: {sorted(missing_shots_top)}")
    if unknown_shots_top:
        errors.append(f"shots.yaml: unknown top-level fields: {sorted(unknown_shots_top)}")

    if shots_doc.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"shots.yaml: schema_version must be {SUPPORTED_SCHEMA_VERSION}, "
            f"got {shots_doc.get('schema_version')!r}"
        )

    shots_raw = shots_doc.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        errors.append("shots.yaml: shots must be a non-empty list")
        return result

    result.shots = [s for s in shots_raw if isinstance(s, dict)]
    seen_shot_ids: set[str] = set()
    review_cache: dict[Path, _ParsedReview] = {}

    for idx, shot in enumerate(shots_raw):
        label = f"shots[{idx}]"
        if not isinstance(shot, dict):
            errors.append(f"shots.yaml: {label} must be a mapping")
            continue

        shot_id = shot.get("id")
        if not is_non_empty_str(shot_id):
            errors.append(f"shots.yaml: {label}.id must be a non-empty string")
            shot_tag = label
        else:
            shot_tag = f"shot {shot_id!r}"
            if shot_id in seen_shot_ids:
                errors.append(f"shots.yaml: duplicate shot id {shot_id!r}")
            seen_shot_ids.add(shot_id)

        missing_shot = REQUIRED_SHOT_KEYS - set(shot.keys())
        unknown_shot = set(shot.keys()) - (REQUIRED_SHOT_KEYS | OPTIONAL_SHOT_KEYS)
        if missing_shot:
            errors.append(f"shots.yaml: {shot_tag} missing required fields: {sorted(missing_shot)}")
        if unknown_shot:
            errors.append(f"shots.yaml: {shot_tag} unknown fields: {sorted(unknown_shot)}")

        for str_field in ("scene", "camera", "action"):
            if str_field in shot and not is_non_empty_str(shot.get(str_field)):
                errors.append(f"shots.yaml: {shot_tag}.{str_field} must be a non-empty string")

        if "sound" in shot and shot["sound"] is not None and not is_non_empty_str(shot["sound"]):
            errors.append(f"shots.yaml: {shot_tag}.sound must be a non-empty string when set")

        if "note" in shot and shot["note"] is not None and not is_non_empty_str(shot["note"]):
            errors.append(f"shots.yaml: {shot_tag}.note must be a non-empty string when set")

        target_duration = shot.get("target_duration")
        target_dur_ok = is_real_number(target_duration) and float(target_duration) > 0
        if not target_dur_ok:
            errors.append(
                f"shots.yaml: {shot_tag}.target_duration must be a positive number, "
                f"got {target_duration!r}"
            )

        shot_kind = shot.get("kind")
        if shot_kind not in VALID_SHOT_KINDS:
            errors.append(
                f"shots.yaml: {shot_tag}.kind must be one of {sorted(VALID_SHOT_KINDS)}, "
                f"got {shot_kind!r}"
            )
        elif shot_kind == "insert" and target_dur_ok and float(target_duration) > 3.0 + 1e-6:
            errors.append(
                f"shots.yaml: {shot_tag} with kind='insert' cannot have target_duration > 3.0s "
                f"(got {target_duration})"
            )

        shot_status = shot.get("status")
        if shot_status not in VALID_SHOT_STATUSES:
            errors.append(
                f"shots.yaml: {shot_tag}.status must be one of {sorted(VALID_SHOT_STATUSES)}, "
                f"got {shot_status!r}"
            )

        refs = shot.get("refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"shots.yaml: {shot_tag}.refs must be a non-empty list")
        else:
            seen_refs: set[str] = set()
            for ref in refs:
                if not is_non_empty_str(ref):
                    errors.append(f"shots.yaml: {shot_tag}.refs contains invalid asset id {ref!r}")
                    continue
                if ref in seen_refs:
                    errors.append(f"shots.yaml: {shot_tag}.refs contains duplicate {ref!r}")
                seen_refs.add(ref)
                if valid_assets and ref not in valid_assets:
                    errors.append(
                        f"shots.yaml: {shot_tag}.refs references undefined asset {ref!r}"
                    )

        should_check_shot_media = check_media and (
            media_shot_ids is None or (is_non_empty_str(shot_id) and shot_id in media_shot_ids)
        )

        # --- Validate candidates ---
        candidates_raw = shot.get("candidates")
        candidates_by_id: dict[str, dict[str, Any]] = {}
        if not isinstance(candidates_raw, list):
            errors.append(f"shots.yaml: {shot_tag}.candidates must be a list")
        else:
            if shot_status in {"candidate", "approved"} and not candidates_raw:
                errors.append(
                    f"shots.yaml: {shot_tag} with status={shot_status!r} must have at least one candidate"
                )
            for c_idx, cand in enumerate(candidates_raw):
                c_label = f"{shot_tag}.candidates[{c_idx}]"
                if not isinstance(cand, dict):
                    errors.append(f"shots.yaml: {c_label} must be a mapping")
                    continue
                missing_c = REQUIRED_CANDIDATE_KEYS - set(cand.keys())
                unknown_c = set(cand.keys()) - (REQUIRED_CANDIDATE_KEYS | OPTIONAL_CANDIDATE_KEYS)
                if missing_c:
                    errors.append(f"shots.yaml: {c_label} missing fields: {sorted(missing_c)}")
                if unknown_c:
                    errors.append(f"shots.yaml: {c_label} unknown fields: {sorted(unknown_c)}")

                cid = cand.get("id")
                if not is_non_empty_str(cid):
                    errors.append(f"shots.yaml: {c_label}.id must be a non-empty string")
                elif cid in candidates_by_id:
                    errors.append(f"shots.yaml: {shot_tag} has duplicate candidate id {cid!r}")
                else:
                    candidates_by_id[cid] = cand

                if not is_non_empty_str(cand.get("engine")):
                    errors.append(f"shots.yaml: {c_label}.engine must be a non-empty string")

                if "note" in cand and cand["note"] is not None and not is_non_empty_str(cand["note"]):
                    errors.append(f"shots.yaml: {c_label}.note must be a non-empty string")

                c_sha = cand.get("sha256")
                c_sha_valid = isinstance(c_sha, str) and bool(SHA256_RE.fullmatch(c_sha))
                if not c_sha_valid:
                    errors.append(
                        f"shots.yaml: {c_label}.sha256 must be a 64-char lowercase hex string"
                    )

                c_file_raw = cand.get("file")
                c_file_path = resolve_confined_path(proj_path, c_file_raw)
                if c_file_path is None or not c_file_path.suffix:
                    errors.append(
                        f"shots.yaml: {c_label}.file must be a relative file path inside project dir, "
                        f"got {c_file_raw!r}"
                    )
                elif should_check_shot_media:
                    if not c_file_path.is_file():
                        errors.append(
                            f"media: {shot_tag} candidate {cid!r} file does not exist: {c_file_raw}"
                        )
                    elif c_sha_valid:
                        actual_c_sha = sha256_file(c_file_path)
                        if actual_c_sha != c_sha:
                            errors.append(
                                f"media: {shot_tag} candidate {cid!r} sha256 mismatch for "
                                f"{c_file_raw}: expected {c_sha}, got {actual_c_sha}"
                            )

        # --- Validate selected ---
        selected = shot.get("selected")
        selected_clip_duration: float | None = None
        selected_cand_obj: dict[str, Any] | None = None
        selected_audio_mode = "source"

        if shot_status == "pending" and selected is not None:
            errors.append(f"shots.yaml: {shot_tag} with status='pending' must have selected=null")

        if shot_status == "approved" and not isinstance(selected, dict):
            errors.append(f"shots.yaml: {shot_tag} with status='approved' must specify selected")

        if selected is not None and not isinstance(selected, dict):
            errors.append(f"shots.yaml: {shot_tag}.selected must be null or a mapping")
        elif isinstance(selected, dict):
            unknown_sel = set(selected.keys()) - ALLOWED_SELECTED_KEYS
            if unknown_sel:
                errors.append(
                    f"shots.yaml: {shot_tag}.selected has unknown fields: {sorted(unknown_sel)}"
                )
            req_sel = {"candidate", "in", "out"}
            if shot_status == "approved":
                req_sel = {"candidate", "in", "out", "audio", "review"}
            missing_sel = req_sel - set(selected.keys())
            if missing_sel:
                errors.append(
                    f"shots.yaml: {shot_tag}.selected missing required fields: {sorted(missing_sel)}"
                )

            sel_cid = selected.get("candidate")
            if not is_non_empty_str(sel_cid):
                errors.append(f"shots.yaml: {shot_tag}.selected.candidate must be a non-empty string")
            elif sel_cid not in candidates_by_id:
                errors.append(
                    f"shots.yaml: {shot_tag}.selected.candidate {sel_cid!r} not found in candidates"
                )
            else:
                selected_cand_obj = candidates_by_id[sel_cid]
                ext = Path(str(selected_cand_obj.get("file", ""))).suffix.lower()
                if shot_kind == "performance" and ext not in VIDEO_EXTENSIONS:
                    errors.append(
                        f"shots.yaml: {shot_tag} is kind='performance' so selected candidate "
                        f"{sel_cid!r} must be a video ({sorted(VIDEO_EXTENSIONS)}), got {ext!r}"
                    )
                elif shot_kind == "insert" and ext not in INSERT_EXTENSIONS:
                    errors.append(
                        f"shots.yaml: {shot_tag} is kind='insert' so selected candidate "
                        f"{sel_cid!r} must be {sorted(INSERT_EXTENSIONS)}, got {ext!r}"
                    )

            in_pt = selected.get("in")
            out_pt = selected.get("out")
            if not is_real_number(in_pt) or not is_real_number(out_pt):
                errors.append(
                    f"shots.yaml: {shot_tag}.selected in/out must be numbers, "
                    f"got in={in_pt!r}, out={out_pt!r}"
                )
            else:
                in_f, out_f = float(in_pt), float(out_pt)
                if in_f < 0 or in_f >= out_f:
                    errors.append(
                        f"shots.yaml: {shot_tag}.selected requires 0 <= in < out, "
                        f"got in={in_f}, out={out_f}"
                    )
                else:
                    selected_clip_duration = out_f - in_f
                    if shot_kind == "insert" and selected_clip_duration > 3.0 + 1e-6:
                        errors.append(
                            f"shots.yaml: {shot_tag} with kind='insert' cannot exceed 3.0s "
                            f"(out - in = {selected_clip_duration:.3f}s)"
                        )

            raw_audio = selected.get("audio", "source")
            if not is_non_empty_str(raw_audio):
                errors.append(f"shots.yaml: {shot_tag}.selected.audio must be a non-empty string")
            else:
                selected_audio_mode = raw_audio
                if raw_audio not in {"source", "mute"} and not raw_audio.startswith("replace:"):
                    errors.append(
                        f"shots.yaml: {shot_tag}.selected.audio must be 'source', 'mute', "
                        f"or 'replace:<file>', got {raw_audio!r}"
                    )
                elif raw_audio.startswith("replace:"):
                    rep_rel = raw_audio.split(":", 1)[1]
                    rep_path = resolve_confined_path(proj_path, rep_rel)
                    if rep_path is None:
                        errors.append(
                            f"shots.yaml: {shot_tag}.selected.audio replace path is invalid: "
                            f"{rep_rel!r}"
                        )
                    elif should_check_shot_media:
                        if not rep_path.is_file():
                            errors.append(
                                f"media: {shot_tag} replacement audio file does not exist: {rep_rel}"
                            )
                        else:
                            try:
                                rep_probe = probe_media(rep_path)
                            except RuntimeError as exc:
                                errors.append(f"media: {shot_tag} {exc}")
                            else:
                                if not rep_probe.has_audio:
                                    errors.append(
                                        f"media: {shot_tag} replacement audio {rep_rel} has no audio stream"
                                    )
                                if (
                                    selected_clip_duration is not None
                                    and rep_probe.duration is not None
                                    and rep_probe.duration + 1e-3 < selected_clip_duration
                                ):
                                    errors.append(
                                        f"media: {shot_tag} replacement audio {rep_rel} duration "
                                        f"({rep_probe.duration:.3f}s) is shorter than clip "
                                        f"({selected_clip_duration:.3f}s)"
                                    )

                if raw_audio == "mute" or raw_audio.startswith("replace:"):
                    combined_note = (
                        selected.get("note")
                        or shot.get("note")
                        or (selected_cand_obj.get("note") if selected_cand_obj else None)
                    )
                    if not is_non_empty_str(combined_note):
                        errors.append(
                            f"shots.yaml: {shot_tag} uses audio={raw_audio!r} and must explain "
                            f"the reason in note"
                        )

            if "crop" in selected and not isinstance(selected["crop"], bool):
                errors.append(f"shots.yaml: {shot_tag}.selected.crop must be a boolean")
            if "fit" in selected and selected["fit"] not in {"pad", "crop"}:
                errors.append(
                    f"shots.yaml: {shot_tag}.selected.fit must be 'pad' or 'crop', "
                    f"got {selected['fit']!r}"
                )
            if (
                "crop" in selected
                and "fit" in selected
                and isinstance(selected["crop"], bool)
                and selected["fit"] in {"pad", "crop"}
            ):
                if selected["crop"] != (selected["fit"] == "crop"):
                    errors.append(
                        f"shots.yaml: {shot_tag}.selected crop={selected['crop']} "
                        f"contradicts fit={selected['fit']!r}"
                    )

            # Validate human review linkage when approved (or whenever review is provided)
            raw_review = selected.get("review")
            if shot_status == "approved" or raw_review is not None:
                reviews_dir = proj_path / "reviews"
                if not is_non_empty_str(raw_review):
                    errors.append(
                        f"shots.yaml: {shot_tag}.selected.review must be a non-empty relative path"
                    )
                else:
                    rel_rv = Path(raw_review)
                    if rel_rv.parts[:1] != ("reviews",):
                        errors.append(
                            f"shots.yaml: {shot_tag}.selected.review must reside under 'reviews/', "
                            f"got {raw_review!r}"
                        )
                    else:
                        sub_rel = str(Path(*rel_rv.parts[1:]))
                        rv_path = resolve_confined_path(reviews_dir, sub_rel)
                        if rv_path is None:
                            errors.append(
                                f"shots.yaml: {shot_tag}.selected.review path is invalid: "
                                f"{raw_review!r}"
                            )
                        else:
                            if rv_path not in review_cache:
                                review_cache[rv_path] = _load_and_validate_review(
                                    rv_path, raw_review, errors
                                )
                            parsed_rv = review_cache[rv_path]
                            if shot_status == "approved" and is_non_empty_str(shot_id):
                                decision = parsed_rv.decisions.get(shot_id)
                                if decision is None:
                                    errors.append(
                                        f"shots.yaml: {shot_tag} is approved, but {raw_review} "
                                        f"has no decision for {shot_id!r}"
                                    )
                                else:
                                    if decision["status"] != "approved":
                                        errors.append(
                                            f"shots.yaml: {shot_tag} is approved, but {raw_review} "
                                            f"records status={decision['status']!r}"
                                        )
                                    if (
                                        is_non_empty_str(sel_cid)
                                        and decision["candidate"] != sel_cid
                                    ):
                                        errors.append(
                                            f"shots.yaml: {shot_tag} selects candidate {sel_cid!r}, "
                                            f"but {raw_review} approved candidate "
                                            f"{decision['candidate']!r}"
                                        )

        if shot_kind == "insert":
            insert_note = (
                shot.get("note")
                or (selected.get("note") if isinstance(selected, dict) else None)
                or (selected_cand_obj.get("note") if selected_cand_obj else None)
            )
            if not is_non_empty_str(insert_note):
                errors.append(
                    f"shots.yaml: {shot_tag} has kind='insert' and must explain its narrative "
                    f"purpose in note"
                )

        # --- Validate dialogue and listener ---
        dialogue_raw = shot.get("dialogue")
        listener = shot.get("listener")
        character_ids = {
            aid for aid, meta in valid_assets.items() if meta.get("kind") == "character"
        }

        if not isinstance(dialogue_raw, list):
            errors.append(f"shots.yaml: {shot_tag}.dialogue must be a list")
        else:
            if dialogue_raw:
                if not is_non_empty_str(listener):
                    errors.append(
                        f"shots.yaml: {shot_tag} has dialogue and must specify listener "
                        f"('none' for monologue)"
                    )
                elif listener != "none" and valid_assets and listener not in character_ids:
                    errors.append(
                        f"shots.yaml: {shot_tag}.listener {listener!r} must be 'none' or a "
                        f"character asset id ({sorted(character_ids)})"
                    )
            elif listener is not None:
                if not is_non_empty_str(listener) or (
                    listener != "none" and valid_assets and listener not in character_ids
                ):
                    errors.append(
                        f"shots.yaml: {shot_tag}.listener {listener!r} must be 'none' or a "
                        f"character asset id"
                    )

            max_dialogue_time: float | None = selected_clip_duration
            if max_dialogue_time is None and target_dur_ok:
                max_dialogue_time = float(target_duration)

            for d_idx, line in enumerate(dialogue_raw):
                d_label = f"{shot_tag}.dialogue[{d_idx}]"
                if not isinstance(line, dict):
                    errors.append(f"shots.yaml: {d_label} must be a mapping")
                    continue
                missing_d = REQUIRED_DIALOGUE_KEYS - set(line.keys())
                unknown_d = set(line.keys()) - REQUIRED_DIALOGUE_KEYS
                if missing_d:
                    errors.append(f"shots.yaml: {d_label} missing fields: {sorted(missing_d)}")
                if unknown_d:
                    errors.append(f"shots.yaml: {d_label} unknown fields: {sorted(unknown_d)}")

                speaker = line.get("speaker")
                if not is_non_empty_str(speaker):
                    errors.append(f"shots.yaml: {d_label}.speaker must be a non-empty string")
                elif valid_assets and speaker not in character_ids:
                    errors.append(
                        f"shots.yaml: {d_label}.speaker {speaker!r} must be a character asset id "
                        f"({sorted(character_ids)})"
                    )
                elif is_non_empty_str(listener) and listener != "none" and speaker == listener:
                    errors.append(
                        f"shots.yaml: {d_label}.speaker {speaker!r} cannot equal listener"
                    )

                if not is_non_empty_str(line.get("text")):
                    errors.append(f"shots.yaml: {d_label}.text must be a non-empty string")

                at_val = line.get("at")
                end_val = line.get("end")
                if not is_real_number(at_val) or not is_real_number(end_val):
                    errors.append(
                        f"shots.yaml: {d_label} at/end must be numbers, "
                        f"got at={at_val!r}, end={end_val!r}"
                    )
                else:
                    at_f, end_f = float(at_val), float(end_val)
                    if at_f < 0 or at_f >= end_f:
                        errors.append(
                            f"shots.yaml: {d_label} requires 0 <= at < end, "
                            f"got at={at_f}, end={end_f}"
                        )
                    elif max_dialogue_time is not None and end_f > max_dialogue_time + 1e-6:
                        bound_desc = (
                            f"out - in ({max_dialogue_time:.3f}s)"
                            if selected_clip_duration is not None
                            else f"target_duration ({max_dialogue_time:.3f}s)"
                        )
                        errors.append(
                            f"shots.yaml: {d_label}.end ({end_f}) exceeds {bound_desc}"
                        )

        # --- Selected candidate stream & duration media checks ---
        if (
            should_check_shot_media
            and isinstance(selected, dict)
            and selected_cand_obj is not None
            and selected_clip_duration is not None
        ):
            sel_rel = str(selected_cand_obj.get("file", ""))
            sel_path = resolve_confined_path(proj_path, sel_rel)
            if sel_path is not None and sel_path.is_file():
                ext = sel_path.suffix.lower()
                try:
                    media_probe = probe_media(sel_path)
                except RuntimeError as exc:
                    errors.append(f"media: {shot_tag} {exc}")
                else:
                    if not media_probe.has_video:
                        errors.append(
                            f"media: {shot_tag} selected file {sel_rel} has no video/image stream"
                        )
                    if ext in VIDEO_EXTENSIONS:
                        out_f = float(selected["out"])
                        if media_probe.duration is None:
                            errors.append(
                                f"media: {shot_tag} could not determine duration of {sel_rel}"
                            )
                        elif out_f > media_probe.duration + 1e-3:
                            errors.append(
                                f"media: {shot_tag} selected out={out_f} exceeds source duration "
                                f"{media_probe.duration:.3f}s ({sel_rel})"
                            )
                    if (
                        isinstance(dialogue_raw, list)
                        and dialogue_raw
                        and selected_audio_mode == "source"
                        and not media_probe.has_audio
                    ):
                        errors.append(
                            f"media: {shot_tag} has dialogue with audio='source', "
                            f"but {sel_rel} has no audio stream"
                        )

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AI wedding film project manifests and review records."
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="Path to project directory (e.g. projects/zaideng)",
    )
    parser.add_argument(
        "--check-media",
        action="store_true",
        help="Verify local candidate media files, SHA-256 digests, trim bounds, and audio streams.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    res = validate_project(args.project_dir, check_media=args.check_media)
    if not res.ok:
        for err in res.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            f"Validation failed for {args.project_dir} with {len(res.errors)} error(s).",
            file=sys.stderr,
        )
        return 1

    mode = "manifest + media" if args.check_media else "manifest"
    print(
        f"OK ({mode}): {res.project.get('slug')} — "
        f"{len(res.project.get('assets', {}))} assets, {len(res.shots)} shots validated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
