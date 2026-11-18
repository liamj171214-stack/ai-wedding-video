"""Integration tests for tools/assemble.py using FFmpeg lavfi test sources."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.assemble import assemble_project
from tools.assemble import main as assemble_cli_main
from tools.validate import probe_media, sha256_file


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        check=True,
    )


def _lavfi_video(
    path: Path,
    *,
    duration: float,
    size: str = "640x360",
    fps: int = 24,
    freq: int = 440,
    with_audio: bool = True,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={fps}:duration={duration}",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={freq}:sample_rate=48000:duration={duration}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
            ]
        )
    else:
        cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"])
    cmd.append(str(path))
    _ffmpeg(*cmd)
    return sha256_file(path)


def _lavfi_image(path: Path, *, color: str = "steelblue", size: str = "640x360") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:size={size}:rate=24",
        "-frames:v",
        "1",
        str(path),
    )
    return sha256_file(path)


def _lavfi_audio(path: Path, *, duration: float, freq: int = 520) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:sample_rate=48000:duration={duration}",
        "-c:a",
        "pcm_s16le",
        str(path),
    )
    return sha256_file(path)


def _probe_video_stream_duration(path: Path) -> tuple[int, float]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,duration",
            "-print_format",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(proc.stdout)["streams"][0]
    frames = int(stream["nb_read_frames"])
    dur = float(stream["duration"])
    return frames, dur


def _assert_full_decode_clean(path: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.strip() == ""


def _write_human_review(path: Path, decisions: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "schema_version": 1,
        "reviewer": "Liam Jia",
        "reviewed_at": "2026-11-18",
        "output_file": "output/cafe-draft.mp4",
        "manifest_commit": "804fee0",
        "decisions": decisions,
    }
    rows = [
        f"| {sid} | {meta['candidate']} | 00:00 | {meta['status']} | 人工审片记录 |"
        for sid, meta in decisions.items()
    ]
    text = "\n".join(
        [
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
            *rows,
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def cafe_test_repo(tmp_path: Path) -> dict[str, Any]:
    """Create a 640x360 @ 24fps test project with lavfi clips."""
    repo_root = tmp_path / "repo"
    proj_dir = repo_root / "projects" / "zaideng"
    proj_dir.mkdir(parents=True)

    lin_sha = _lavfi_image(repo_root / "examples/cafe/assets/lin.jpg", color="tan")
    zhou_sha = _lavfi_image(repo_root / "examples/cafe/assets/zhou.jpg", color="navy")
    cafe_sha = _lavfi_image(repo_root / "examples/cafe/assets/cafe.jpg", color="saddlebrown")

    project_doc = {
        "schema_version": 1,
        "slug": "zaideng",
        "title": "再等一班",
        "fps": 24,
        "resolution": "640x360",
        "assets": {
            "lin": {
                "path": "examples/cafe/assets/lin.jpg",
                "kind": "character",
                "version": 1,
                "sha256": lin_sha,
            },
            "zhou": {
                "path": "examples/cafe/assets/zhou.jpg",
                "kind": "character",
                "version": 1,
                "sha256": zhou_sha,
            },
            "cafe": {
                "path": "examples/cafe/assets/cafe.jpg",
                "kind": "set",
                "version": 1,
                "sha256": cafe_sha,
            },
        },
    }
    (proj_dir / "project.yaml").write_text(
        yaml.safe_dump(project_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"repo_root": repo_root, "proj_dir": proj_dir, "project": project_doc}


def test_release_mode_rejects_unapproved_shots(cafe_test_repo: dict[str, Any]) -> None:
    proj_dir = cafe_test_repo["proj_dir"]
    clip_sha = _lavfi_video(proj_dir / "input/15a/c1.mp4", duration=3.0, freq=400)

    shots_doc = {
        "schema_version": 1,
        "shots": [
            {
                "id": "15a",
                "scene": "次日咖啡角",
                "camera": "A",
                "target_duration": 2.0,
                "action": "周远推茶",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "candidate",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "flow",
                        "file": "input/15a/c1.mp4",
                        "sha256": clip_sha,
                    }
                ],
                "selected": None,
            },
            {
                "id": "15b",
                "scene": "次日咖啡角",
                "camera": "B",
                "target_duration": 2.0,
                "action": "周远道歉",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "pending",
                "candidates": [],
                "selected": None,
            },
        ],
    }
    (proj_dir / "shots.yaml").write_text(
        yaml.safe_dump(shots_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Release mode requires all selected shots"):
        assemble_project(proj_dir, draft=False)

    assert assemble_cli_main([str(proj_dir)]) == 1


def test_draft_mode_inserts_placeholder_card_and_uses_first_candidate(
    cafe_test_repo: dict[str, Any],
) -> None:
    proj_dir = cafe_test_repo["proj_dir"]
    sha_15a = _lavfi_video(proj_dir / "input/15a/c1.mp4", duration=2.0, freq=380)
    sha_15c = _lavfi_video(proj_dir / "input/15c/c1.mp4", duration=2.5, freq=520)

    _write_human_review(
        proj_dir / "reviews/20261118-15a.md",
        {"15a": {"candidate": "c1", "status": "approved"}},
    )

    shots_doc = {
        "schema_version": 1,
        "shots": [
            {
                "id": "15a",
                "scene": "次日咖啡角",
                "camera": "A",
                "target_duration": 2.0,
                "action": "周远推茶",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "approved",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "flow",
                        "file": "input/15a/c1.mp4",
                        "sha256": sha_15a,
                    }
                ],
                "selected": {
                    "candidate": "c1",
                    "in": 0.25,
                    "out": 1.75,
                    "audio": "source",
                    "review": "reviews/20261118-15a.md",
                },
            },
            {
                "id": "15b",
                "scene": "次日咖啡角",
                "camera": "B",
                "target_duration": 2.0,
                "action": "周远道歉",
                "dialogue": [
                    {
                        "speaker": "zhou",
                        "at": 0.2,
                        "end": 1.8,
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
            {
                "id": "15c",
                "scene": "次日咖啡角",
                "camera": "C",
                "target_duration": 2.5,
                "action": "林夏回应",
                "dialogue": [
                    {
                        "speaker": "lin",
                        "at": 0.5,
                        "end": 2.0,
                        "text": "茶喝完再走。",
                    }
                ],
                "listener": "zhou",
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "candidate",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "flow",
                        "file": "input/15c/c1.mp4",
                        "sha256": sha_15c,
                    }
                ],
                "selected": None,
            },
        ],
    }
    (proj_dir / "shots.yaml").write_text(
        yaml.safe_dump(shots_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    rc = assemble_cli_main([str(proj_dir), "--draft", "--date", "20261118"])
    assert rc == 0

    out_mp4 = proj_dir / "output" / "zaideng-15a-15c-20261118-draft.mp4"
    edl_path = proj_dir / "build" / "edl.json"
    srt_path = proj_dir / "build" / "subs.srt"
    missing_card = proj_dir / "build" / "cards" / "missing-15b.png"

    assert out_mp4.is_file()
    assert edl_path.is_file()
    assert srt_path.is_file()
    assert missing_card.is_file()
    assert missing_card.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    assert edl["mode"] == "draft"
    assert [s["mode"] for s in edl["shots"]] == ["selected", "placeholder", "draft_candidate"]
    assert edl["shots"][1]["id"] == "15b"
    assert edl["shots"][1]["duration"] == pytest.approx(2.0, abs=1e-6)

    # Expected total: 1.5s (15a) + 2.0s (15b card) + 2.5s (15c untrimmed candidate) = 6.0s
    frames, v_dur = _probe_video_stream_duration(out_mp4)
    assert frames == int(round(6.0 * 24))
    assert abs(v_dur - 6.0) <= 1.0 / 24.0
    _assert_full_decode_clean(out_mp4)

    # Verify SRT offsets: 15b starts at 1.500s -> 00:00:01,700 --> 00:00:03,300
    # 15c starts at 3.500s -> 00:00:04,000 --> 00:00:05,500
    srt_text = srt_path.read_text(encoding="utf-8")
    assert "00:00:01,700 --> 00:00:03,300" in srt_text
    assert "昨天让你白等了。" in srt_text
    assert "00:00:04,000 --> 00:00:05,500" in srt_text
    assert "茶喝完再走。" in srt_text


def test_release_trim_accuracy_within_one_frame_and_full_decode(
    cafe_test_repo: dict[str, Any],
) -> None:
    proj_dir = cafe_test_repo["proj_dir"]
    # Different input aspect ratios (480x360 4:3 and 800x450 16:9) normalized to 640x360 @ 24fps
    sha_a = _lavfi_video(
        proj_dir / "input/15a/c1.mp4", duration=4.0, size="480x360", fps=30, freq=330
    )
    sha_b = _lavfi_video(
        proj_dir / "input/15b/c1.mp4", duration=5.0, size="800x450", fps=24, freq=440
    )
    sha_ins = _lavfi_image(proj_dir / "input/15c/ticket.jpg", color="wheat", size="500x500")
    _lavfi_audio(proj_dir / "input/15c/paper.wav", duration=2.0, freq=600)

    _write_human_review(
        proj_dir / "reviews/20261118-release.md",
        {
            "15a": {"candidate": "c1", "status": "approved"},
            "15b": {"candidate": "c1", "status": "approved"},
            "15c": {"candidate": "c1", "status": "approved"},
        },
    )

    # Trims (including non-frame-aligned 0.4 -> 2.5 = 2.1s = 50.4 frames @ 24fps):
    # 15a: 0.40 -> 2.50 = 2.10s (50 frames = 2.0833s @ 24fps)
    # 15b: 0.40 -> 2.90 = 2.50s (60 frames @ 24fps), explicit crop=True
    # 15c: 0.00 -> 1.25 = 1.25s (30 frames @ 24fps), insert image + replace audio
    # Total requested = 5.85s (140 frames = 5.8333s @ 24fps), trailing pending shot 15d excluded by --shots 15a-15c
    shots_doc = {
        "schema_version": 1,
        "shots": [
            {
                "id": "15a",
                "scene": "次日咖啡角",
                "camera": "A",
                "target_duration": 2.0,
                "action": "周远推茶",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "approved",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "flow",
                        "file": "input/15a/c1.mp4",
                        "sha256": sha_a,
                    }
                ],
                "selected": {
                    "candidate": "c1",
                    "in": 0.40,
                    "out": 2.50,
                    "audio": "source",
                    "review": "reviews/20261118-release.md",
                },
            },
            {
                "id": "15b",
                "scene": "次日咖啡角",
                "camera": "B",
                "target_duration": 3.0,
                "action": "周远道歉",
                "dialogue": [
                    {
                        "speaker": "zhou",
                        "at": 0.2,
                        "end": 2.2,
                        "text": "以后来不了，我先告诉你。",
                    }
                ],
                "listener": "lin",
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "approved",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "flow",
                        "file": "input/15b/c1.mp4",
                        "sha256": sha_b,
                    }
                ],
                "selected": {
                    "candidate": "c1",
                    "in": 0.40,
                    "out": 2.90,
                    "audio": "source",
                    "crop": True,
                    "review": "reviews/20261118-release.md",
                },
            },
            {
                "id": "15c",
                "scene": "次日咖啡角",
                "camera": "C",
                "target_duration": 1.5,
                "action": "车票折角特写",
                "note": "车票折角短插入承接回忆",
                "dialogue": [],
                "refs": ["cafe"],
                "kind": "insert",
                "status": "approved",
                "candidates": [
                    {
                        "id": "c1",
                        "engine": "imagegen",
                        "file": "input/15c/ticket.jpg",
                        "sha256": sha_ins,
                    }
                ],
                "selected": {
                    "candidate": "c1",
                    "in": 0.0,
                    "out": 1.25,
                    "audio": "replace:input/15c/paper.wav",
                    "note": "加入纸票翻动拟音",
                    "review": "reviews/20261118-release.md",
                },
            },
            {
                "id": "15d",
                "scene": "次日咖啡角",
                "camera": "A",
                "target_duration": 4.0,
                "action": "两人碰杯",
                "dialogue": [],
                "refs": ["lin", "zhou", "cafe"],
                "kind": "performance",
                "status": "pending",
                "candidates": [],
                "selected": None,
            },
        ],
    }
    (proj_dir / "shots.yaml").write_text(
        yaml.safe_dump(shots_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    outputs = assemble_project(
        proj_dir,
        draft=False,
        shots_spec="15a-15c",
        date_tag="20261118",
    )
    assert outputs.output_mp4.name == "zaideng-15a-15c-20261118.mp4"
    assert outputs.output_mp4.is_file()

    expected_duration = (2.50 - 0.40) + (2.90 - 0.40) + (1.25 - 0.0)  # 5.85s
    frames, v_dur = _probe_video_stream_duration(outputs.output_mp4)
    info = probe_media(outputs.output_mp4)

    assert info.width == 640 and info.height == 360
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.fps is not None and abs(info.fps - 24.0) < 0.05
    assert frames == 140
    assert abs(v_dur - expected_duration) <= 1.0 / 24.0
    assert info.duration is not None
    assert abs(info.duration - expected_duration) <= 1.0 / 24.0

    _assert_full_decode_clean(outputs.output_mp4)
