"""Unit and integration tests for tools/validate.py (pass and fail for every rule)."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.validate import main as validate_cli_main
from tools.validate import sha256_file, validate_project


def _run_ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        check=True,
    )


def _make_video(path: Path, *, duration: float = 3.0, with_audio: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x180:rate=24:duration={duration}",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={duration}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
            ]
        )
    else:
        cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"])
    cmd.append(str(path))
    _run_ffmpeg(*cmd)
    return sha256_file(path)


def _make_audio(path: Path, *, duration: float = 3.0) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=660:sample_rate=48000:duration={duration}",
        "-c:a",
        "pcm_s16le",
        str(path),
    )
    return sha256_file(path)


def _make_image(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=navy:size=320x180:rate=24",
        "-frames:v",
        "1",
        str(path),
    )
    return sha256_file(path)


def _write_review(
    review_path: Path,
    *,
    reviewer: str = "liam-director",
    reviewed_at: str = "2026-11-18",
    decisions: dict[str, dict[str, str]] | None = None,
    table_rows: list[tuple[str, str, str, str]] | None = None,
) -> None:
    review_path.parent.mkdir(parents=True, exist_ok=True)
    if decisions is None:
        decisions = {"01a": {"candidate": "c1", "status": "approved"}}
    fm = {
        "schema_version": 1,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "output_file": "output/demo-01a-20261118-draft.mp4",
        "manifest_commit": "804fee0",
        "decisions": decisions,
    }
    if table_rows is None:
        table_rows = [
            (sid, entry["candidate"], "00:00-00:02", entry["status"])
            for sid, entry in decisions.items()
        ]
    lines = [
        "---",
        yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
        "# 场次审片",
        "",
        "## 逐镜结论",
        "",
        "| 镜号 | 候选 | 成片时间点 | 结论（approved / reshoot / reselect） | 问题与依据 |",
        "|---|---|---|---|---|",
    ]
    for sid, cand, span, verdict in table_rows:
        lines.append(f"| {sid} | {cand} | {span} | {verdict} | 人工核验记录 |")
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def sandbox_project(tmp_path: Path) -> dict[str, Any]:
    """Create a minimal valid repo + project structure in tmp_path."""
    repo_root = tmp_path / "repo"
    proj_dir = repo_root / "projects" / "demo"
    proj_dir.mkdir(parents=True)

    lin_img = repo_root / "examples" / "assets" / "lin.jpg"
    zhou_img = repo_root / "examples" / "assets" / "zhou.jpg"
    cafe_img = repo_root / "examples" / "assets" / "cafe.jpg"
    lin_sha = _make_image(lin_img)
    zhou_sha = _make_image(zhou_img)
    cafe_sha = _make_image(cafe_img)

    project_data = {
        "schema_version": 1,
        "slug": "demo",
        "title": "测试项目",
        "fps": 24,
        "resolution": "1920x1080",
        "assets": {
            "lin": {
                "path": "examples/assets/lin.jpg",
                "kind": "character",
                "version": 1,
                "sha256": lin_sha,
            },
            "zhou": {
                "path": "examples/assets/zhou.jpg",
                "kind": "character",
                "version": 1,
                "sha256": zhou_sha,
            },
            "cafe": {
                "path": "examples/assets/cafe.jpg",
                "kind": "set",
                "version": 1,
                "sha256": cafe_sha,
            },
        },
    }

    shots_data = {
        "schema_version": 1,
        "shots": [
            {
                "id": "01a",
                "scene": "次日咖啡角",
                "camera": "A",
                "target_duration": 2.5,
                "action": "周远推茶，林夏看杯子",
                "sound": "安静室内底声与推杯声",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "pending",
                "candidates": [],
                "selected": None,
            },
            {
                "id": "01b",
                "scene": "次日咖啡角",
                "camera": "B",
                "target_duration": 4.0,
                "action": "周远开口道歉，林夏倾听",
                "dialogue": [
                    {
                        "speaker": "zhou",
                        "at": 0.4,
                        "end": 3.5,
                        "text": "昨天让你白等了。",
                    }
                ],
                "listener": "lin",
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "pending",
                "candidates": [],
                "selected": None,
            },
        ],
    }

    def save(proj: dict[str, Any] | None = None, shots: dict[str, Any] | None = None) -> None:
        if proj is not None:
            (proj_dir / "project.yaml").write_text(
                yaml.safe_dump(proj, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        if shots is not None:
            (proj_dir / "shots.yaml").write_text(
                yaml.safe_dump(shots, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

    save(project_data, shots_data)
    return {
        "repo_root": repo_root,
        "proj_dir": proj_dir,
        "project": project_data,
        "shots": shots_data,
        "save": save,
    }


def test_real_zaideng_manifest_passes() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zaideng_dir = repo_root / "projects" / "zaideng"
    res = validate_project(zaideng_dir)
    assert res.ok, res.errors
    assert validate_cli_main([str(zaideng_dir)]) == 0


def test_schema_fields_and_unique_shot_ids_pass_and_fail(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]
    assert validate_project(proj_dir).ok

    # Fail: wrong schema_version
    bad_proj = copy.deepcopy(sandbox_project["project"])
    bad_proj["schema_version"] = 2
    sandbox_project["save"](proj=bad_proj)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("schema_version" in e for e in res.errors)
    sandbox_project["save"](proj=sandbox_project["project"])

    # Fail: duplicate shot id and unknown shot field
    bad_shots = copy.deepcopy(sandbox_project["shots"])
    bad_shots["shots"][1]["id"] = "01a"
    bad_shots["shots"][0]["unexpected_field"] = 123
    sandbox_project["save"](shots=bad_shots)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("duplicate shot id" in e for e in res.errors)
    assert any("unknown fields" in e for e in res.errors)


def test_asset_refs_existence_and_sha256_pass_and_fail(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]
    assert validate_project(proj_dir).ok

    # Fail: shot references undefined asset
    bad_shots = copy.deepcopy(sandbox_project["shots"])
    bad_shots["shots"][0]["refs"].append("nonexistent_prop")
    sandbox_project["save"](shots=bad_shots)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("undefined asset" in e for e in res.errors)
    sandbox_project["save"](shots=sandbox_project["shots"])

    # Fail: asset sha256 mismatch
    bad_proj = copy.deepcopy(sandbox_project["project"])
    bad_proj["assets"]["lin"]["sha256"] = "0" * 64
    sandbox_project["save"](proj=bad_proj)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("sha256 mismatch" in e for e in res.errors)

    # Fail: missing asset file & path traversal
    bad_proj2 = copy.deepcopy(sandbox_project["project"])
    bad_proj2["assets"]["lin"]["path"] = "examples/assets/missing.jpg"
    bad_proj2["assets"]["cafe"]["path"] = "../outside.jpg"
    sandbox_project["save"](proj=bad_proj2)
    res2 = validate_project(proj_dir)
    assert not res2.ok
    assert any("does not exist" in e for e in res2.errors)
    assert any("relative path inside repo root" in e for e in res2.errors)


def test_approved_shot_and_human_review_pass_and_fail(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]
    shots = copy.deepcopy(sandbox_project["shots"])

    # Pass: approved shot with valid candidate, in < out, and matching human review
    review_rel = "reviews/20261118-01a.md"
    _write_review(
        proj_dir / review_rel,
        reviewer="Liam Jia",
        reviewed_at="2026-11-18",
        decisions={"01a": {"candidate": "c1", "status": "approved"}},
    )
    shots["shots"][0]["status"] = "approved"
    shots["shots"][0]["candidates"] = [
        {
            "id": "c1",
            "engine": "flow-omni-1.2-flash",
            "file": "input/01a/c1.mp4",
            "sha256": "a" * 64,
        }
    ]
    shots["shots"][0]["selected"] = {
        "candidate": "c1",
        "in": 0.2,
        "out": 2.2,
        "audio": "source",
        "review": review_rel,
    }
    sandbox_project["save"](shots=shots)
    assert validate_project(proj_dir, check_media=False).ok

    # Fail 1: approved without selected
    s_no_sel = copy.deepcopy(shots)
    s_no_sel["shots"][0]["selected"] = None
    sandbox_project["save"](shots=s_no_sel)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("must specify selected" in e for e in res.errors)

    # Fail 2: in >= out and missing candidate id
    s_bad_bounds = copy.deepcopy(shots)
    s_bad_bounds["shots"][0]["selected"]["in"] = 2.5
    s_bad_bounds["shots"][0]["selected"]["out"] = 2.0
    s_bad_bounds["shots"][0]["selected"]["candidate"] = "c99"
    sandbox_project["save"](shots=s_bad_bounds)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("0 <= in < out" in e for e in res.errors)
    assert any("not found in candidates" in e for e in res.errors)

    # Fail 3: reviewer is an automated agent / bot
    _write_review(
        proj_dir / review_rel,
        reviewer="claude-agent",
        reviewed_at="2026-11-18",
        decisions={"01a": {"candidate": "c1", "status": "approved"}},
    )
    sandbox_project["save"](shots=shots)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("reviewer must be a non-empty human identifier" in e for e in res.errors)

    # Fail 4: review decision status is reshoot or candidate mismatch
    _write_review(
        proj_dir / review_rel,
        reviewer="Liam Jia",
        reviewed_at="2026-11-18",
        decisions={"01a": {"candidate": "c2", "status": "reshoot"}},
    )
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("status='reshoot'" in e for e in res.errors)
    assert any("approved candidate 'c2'" in e for e in res.errors)

    # Fail 5: markdown table disagrees with frontmatter decisions
    _write_review(
        proj_dir / review_rel,
        reviewer="Liam Jia",
        reviewed_at="2026-11-18",
        decisions={"01a": {"candidate": "c1", "status": "approved"}},
        table_rows=[("01a", "c1", "00:00-00:02", "reshoot")],
    )
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("disagrees with frontmatter" in e for e in res.errors)

    # Fail 6: unedited docs/templates/review.md copied directly is rejected
    template_src = Path(__file__).resolve().parent.parent / "docs" / "templates" / "review.md"
    (proj_dir / review_rel).write_text(template_src.read_text(encoding="utf-8"), encoding="utf-8")
    res_tpl = validate_project(proj_dir)
    assert not res_tpl.ok
    assert any("reviewer" in e for e in res_tpl.errors)
    assert any("reviewed_at" in e for e in res_tpl.errors)


def test_performance_vs_insert_media_and_duration_rules(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]
    review_rel = "reviews/20261118-insert.md"
    _write_review(
        proj_dir / review_rel,
        reviewer="Liam Jia",
        reviewed_at="2026-11-18",
        decisions={"01a": {"candidate": "c1", "status": "approved"}},
    )

    # Fail: performance shot selecting a .jpg image
    shots_perf_img = copy.deepcopy(sandbox_project["shots"])
    shots_perf_img["shots"][0]["status"] = "approved"
    shots_perf_img["shots"][0]["candidates"] = [
        {"id": "c1", "engine": "imagegen", "file": "input/01a/still.jpg", "sha256": "b" * 64}
    ]
    shots_perf_img["shots"][0]["selected"] = {
        "candidate": "c1",
        "in": 0.0,
        "out": 2.0,
        "audio": "mute",
        "note": "静音测试",
        "review": review_rel,
    }
    sandbox_project["save"](shots=shots_perf_img)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("kind='performance'" in e for e in res.errors)

    # Pass: kind='insert' with image, <= 3.0s, and narrative note
    shots_insert_ok = copy.deepcopy(shots_perf_img)
    shots_insert_ok["shots"][0]["kind"] = "insert"
    shots_insert_ok["shots"][0]["target_duration"] = 2.0
    shots_insert_ok["shots"][0]["note"] = "车票折角短插入交代回忆转场"
    sandbox_project["save"](shots=shots_insert_ok)
    assert validate_project(proj_dir).ok

    # Fail: kind='insert' > 3.0s or missing narrative note
    shots_insert_bad = copy.deepcopy(shots_insert_ok)
    shots_insert_bad["shots"][0]["target_duration"] = 3.5
    shots_insert_bad["shots"][0]["selected"]["out"] = 3.5
    del shots_insert_bad["shots"][0]["note"]
    del shots_insert_bad["shots"][0]["selected"]["note"]
    shots_insert_bad["shots"][0]["selected"]["audio"] = "source"
    sandbox_project["save"](shots=shots_insert_bad)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("cannot have target_duration > 3.0s" in e for e in res.errors)
    assert any("narrative purpose in note" in e for e in res.errors)


def test_dialogue_listener_and_timing_bounds_pass_and_fail(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]

    # Pass: monologue with listener='none'
    shots_mono = copy.deepcopy(sandbox_project["shots"])
    shots_mono["shots"][1]["listener"] = "none"
    sandbox_project["save"](shots=shots_mono)
    assert validate_project(proj_dir).ok

    # Fail: dialogue without listener, and dialogue end > target_duration when unselected
    shots_no_listener = copy.deepcopy(sandbox_project["shots"])
    del shots_no_listener["shots"][1]["listener"]
    shots_no_listener["shots"][1]["dialogue"][0]["end"] = 4.5  # target_duration is 4.0
    sandbox_project["save"](shots=shots_no_listener)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("must specify listener" in e for e in res.errors)
    assert any("exceeds target_duration" in e for e in res.errors)

    # Fail: dialogue end > (out - in) when selected
    shots_sel_overflow = copy.deepcopy(sandbox_project["shots"])
    shots_sel_overflow["shots"][1]["status"] = "candidate"
    shots_sel_overflow["shots"][1]["candidates"] = [
        {"id": "c1", "engine": "flow", "file": "input/01b/c1.mp4", "sha256": "c" * 64}
    ]
    shots_sel_overflow["shots"][1]["selected"] = {
        "candidate": "c1",
        "in": 1.0,
        "out": 3.5,  # out - in = 2.5 < end (3.5)
        "audio": "source",
    }
    sandbox_project["save"](shots=shots_sel_overflow)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("exceeds out - in" in e for e in res.errors)


def test_audio_replace_and_mute_require_note(sandbox_project: dict[str, Any]) -> None:
    proj_dir = sandbox_project["proj_dir"]
    shots = copy.deepcopy(sandbox_project["shots"])
    shots["shots"][0]["status"] = "candidate"
    shots["shots"][0]["candidates"] = [
        {"id": "c1", "engine": "flow", "file": "input/01a/c1.mp4", "sha256": "d" * 64}
    ]
    shots["shots"][0]["selected"] = {
        "candidate": "c1",
        "in": 0.0,
        "out": 2.0,
        "audio": "mute",
    }
    sandbox_project["save"](shots=shots)
    res = validate_project(proj_dir)
    assert not res.ok
    assert any("must explain the reason in note" in e for e in res.errors)

    shots["shots"][0]["selected"]["note"] = "推杯原声有底噪，改用静音"
    sandbox_project["save"](shots=shots)
    assert validate_project(proj_dir).ok


def test_check_media_existence_hash_duration_and_audio_stream(
    sandbox_project: dict[str, Any],
) -> None:
    proj_dir = sandbox_project["proj_dir"]
    clip_a = proj_dir / "input" / "01a" / "c1.mp4"
    clip_b = proj_dir / "input" / "01b" / "c1.mp4"
    alt_wav = proj_dir / "input" / "01a" / "foley.wav"

    sha_a = _make_video(clip_a, duration=3.0, with_audio=False)
    sha_b = _make_video(clip_b, duration=4.2, with_audio=True)
    _make_audio(alt_wav, duration=2.5)

    review_rel = "reviews/20261118-all.md"
    _write_review(
        proj_dir / review_rel,
        reviewer="Liam Jia",
        reviewed_at="2026-11-18",
        decisions={
            "01a": {"candidate": "c1", "status": "approved"},
            "01b": {"candidate": "c1", "status": "approved"},
        },
    )

    shots = copy.deepcopy(sandbox_project["shots"])
    shots["shots"][0]["status"] = "approved"
    shots["shots"][0]["candidates"] = [
        {"id": "c1", "engine": "flow", "file": "input/01a/c1.mp4", "sha256": sha_a}
    ]
    shots["shots"][0]["selected"] = {
        "candidate": "c1",
        "in": 0.2,
        "out": 2.2,
        "audio": "replace:input/01a/foley.wav",
        "note": "补录干净木桌推杯声",
        "review": review_rel,
    }
    shots["shots"][1]["status"] = "approved"
    shots["shots"][1]["candidates"] = [
        {"id": "c1", "engine": "flow", "file": "input/01b/c1.mp4", "sha256": sha_b}
    ]
    shots["shots"][1]["selected"] = {
        "candidate": "c1",
        "in": 0.0,
        "out": 4.0,
        "audio": "source",
        "review": review_rel,
    }
    sandbox_project["save"](shots=shots)

    # Pass: all media files exist, sha256 matches, trim <= duration, dialogue has audio
    res_ok = validate_project(proj_dir, check_media=True)
    assert res_ok.ok, res_ok.errors
    assert validate_cli_main([str(proj_dir), "--check-media"]) == 0

    # Fail 1: out exceeds source video duration
    bad_trim = copy.deepcopy(shots)
    bad_trim["shots"][1]["selected"]["out"] = 5.0  # source is 4.2s
    sandbox_project["save"](shots=bad_trim)
    res_trim = validate_project(proj_dir, check_media=True)
    assert not res_trim.ok
    assert any("exceeds source duration" in e for e in res_trim.errors)

    # Fail 2: dialogue shot with audio='source' has no audio stream
    silent_b = proj_dir / "input" / "01b" / "silent.mp4"
    sha_silent_b = _make_video(silent_b, duration=4.2, with_audio=False)
    bad_audio = copy.deepcopy(shots)
    bad_audio["shots"][1]["candidates"][0] = {
        "id": "c1",
        "engine": "flow",
        "file": "input/01b/silent.mp4",
        "sha256": sha_silent_b,
    }
    sandbox_project["save"](shots=bad_audio)
    res_no_audio = validate_project(proj_dir, check_media=True)
    assert not res_no_audio.ok
    assert any("has no audio stream" in e for e in res_no_audio.errors)

    # Fail 3: candidate sha256 mismatch and missing candidate file under --check-media
    bad_hash = copy.deepcopy(shots)
    bad_hash["shots"][0]["candidates"][0]["sha256"] = "f" * 64
    bad_hash["shots"][1]["candidates"].append(
        {"id": "c2", "engine": "grok", "file": "input/01b/missing.mp4", "sha256": "e" * 64}
    )
    sandbox_project["save"](shots=bad_hash)
    assert validate_project(proj_dir, check_media=False).ok
    res_hash = validate_project(proj_dir, check_media=True)
    assert not res_hash.ok
    assert any("sha256 mismatch" in e for e in res_hash.errors)
    assert any("missing.mp4" in e for e in res_hash.errors)
