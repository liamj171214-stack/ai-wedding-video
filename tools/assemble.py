#!/usr/bin/env python3
"""Assemble validated shots into a draft or release MP4, EDL JSON, and SRT subtitles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any
import zlib

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate import (  # noqa: E402
    IMAGE_EXTENSIONS,
    RESOLUTION_RE,
    VIDEO_EXTENSIONS,
    ProbeInfo,
    probe_media,
    resolve_confined_path,
    select_shot_range,
    sha256_file,
    validate_project,
)

# Pre-baked 24px-tall glyph bitmasks (hex row strings) for zero-dependency PNG placeholder cards.
_BITMAP_GLYPHS: dict[str, tuple[int, str]] = {
    ' ': (14, '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'),
    '#': (14, '00000000000001880198019801180ffe03100310031003300ffc02300230022006200620000000000000000000000000'),
    '-': (14, '0000000000000000000000000000000007e0000000000000000000000000000000000000000000000000000000000000'),
    '.': (14, '00000000000000000000000000000000000000c000c000c0000000000000000000000000000000000000000000000000'),
    '0': (14, '000000000000000003e007f00c180c180c08080c180c180c180c080c0c080c180c1807f003e000000000000000000000'),
    '1': (14, '000000000000000003c003c000c000c000c000c000c000c000c000c000c000c000c000c000c000000000000000000000'),
    '2': (14, '000000000000000003e007700c180c180818001800180030006000c001800380070007fc0ffc00000000000000000000'),
    '3': (14, '000000000000000003e007f00e300c180018007001e001f000380018000808080c18063003e000000000000000000000'),
    '4': (14, '0000000000000000001000300030007000f001f001b00330073006300ffc0ffc00300030003000000000000000000000'),
    '5': (14, '000000000000000003f803f803000300020007c007f000180018001800180c180e3807f003e000000000000000000000'),
    '6': (14, '000000000000000000200060006000c00180018003c007f006180c180c080c180e1807f803f000000000000000000000'),
    '7': (14, '00000000000000000ffc0ff80018003000200060004000c0008001800300030006000600040000000000000000000000'),
    '8': (14, '000000000000000003e007f00c180c180c18063003e007f00c180c18080c0c080c1807f803e000000000000000000000'),
    '9': (14, '000000000000000003e007700c180c180c180c180e3807f003f0006000c0018001800300020000000000000000000000'),
    ':': (14, '00000000000000000000000000c000c000000000000000000000000000c000c000c00000000000000000000000000000'),
    'A': (14, '00000000000000000080018001c003c003600260063004300ff80ff8180c180c300c3006200600000000000000000000'),
    'B': (14, '000000000000000007c007f0043004300430047007e007f004380418040c041c043807f007e000000000000000000000'),
    'C': (14, '000000000000000003f807fe0e071803380030003000300030003000380018010e0707fe03f800000000000000000000'),
    'D': (14, '00000000000000001fc01ff01038101c100c10061006100610061006100e100c10381ff81fe000000000000000000000'),
    'E': (14, '000000000000000007f807f8040004000400040007f807f80400040004000400040007f807f800000000000000000000'),
    'F': (14, '000000000000000003f803f8020002000200020003f803f8020002000200020002000200020000000000000000000000'),
    'G': (14, '00000000000001e007fc1e1e38073000200020002000203f203f3001300338071e0e0ffc03f000000000000000000000'),
    'H': (14, '0000000000000000080c080c080c080c080c080c0ffc0ffc080c080c080c080c080c080c080c00000000000000000000'),
    'I': (14, '000000000000000001800180018001800180018001800180018001800180018001800180018000000000000000000000'),
    'J': (14, '0000000000000000003000300030003000300030003000300030003000300030043007e003c000000000000000000000'),
    'K': (14, '0000000000000000041c0438047004e005c0078007000700078005c004e0047004380418040c00000000000000000000'),
    'L': (14, '0000000000000000020002000200020002000200020002000200020002000200020003f803f800000000000000000000'),
    'M': (14, '000000000000000010001003180338073c073c0f360d36193319233121b121e120e120c1204000000000000000000000'),
    'N': (14, '0000000000000000100c100c180c1c0c1e0c170c138c11cc10cc106c103c101c101c100c100400000000000000000000'),
    'O': (14, '000000000000000003f00ff81c1c38063007200320032001200120032003300618060c1c07f000000000000000000000'),
    'P': (14, '000000000000000007f007f8041c040c040c041c07f807f0040004000400040004000400040000000000000000000000'),
    'Q': (14, '000000000000000007f00e1c180e30062003200320012001206320733033381e1c1c0ffc03f600030000000000000000'),
    'R': (14, '000000000000000007f007f8041c040c040c041c07f807f005c004c00460043004380418040c00000000000000000000'),
    'S': (14, '00000000000001c003f00730061006000700038001c000600030001800180c18063007f001e000000000000000000000'),
    'T': (14, '00000000000000000ff00ff0018001800180018001800180018001800180018001800180018000000000000000000000'),
    'U': (14, '0000000000000000080c080c080c080c080c080c080c080c080c08080c080c180e3807f003e000000000000000000000'),
    'V': (14, '00000000000000001806180618060c0c0c0c0618061802300330033001e001e000c000c0008000000000000000000000'),
    'W': (14, '00000000000000000081008101c121c121e323632363363236363e1e1c1e1c1c180c180c080000000000000000000000'),
    'X': (14, '00000000000000000c0c060c0618033003b001e000e000c001e001f00330071806180c0c0c0e00000000000000000000'),
    'Y': (14, '00000000000000000c0c0c0c06180730033001e001e000c000c000c000c000c000c000c000c000000000000000000000'),
    'Z': (14, '000000000000000007f807f0003000200060006000c000c00180018003000300060007f80ff800000000000000000000'),
    '_': (14, '000000000000000000000000000000000000000000000ffc000000000000000000000000000000000000000000000000'),
    'a': (14, '00000000000000000000000003e40e3c0c1c180c18041804180c180c0c1c0f7c03e40000000000000000000000000000'),
    'b': (14, '0000000000000000180018001800180019f01f181c0c18041806180618061c0e1c0c1ff81bf000000000000000000000'),
    'c': (14, '0000000000000000000003e007f80e1c1c0818001800180018001c080e1c07f803e00000000000000000000000000000'),
    'd': (14, '0000000000000000000400040004000403e4063c0c0c180c180418041804180c0c1c0f7c03e400000000000000000000'),
    'e': (14, '00000000000000000000000003e007f00e381c1c180c1ffc180018001c0c0e3807f003e0000000000000000000000000'),
    'f': (14, '000000000000000000e001e00180018003e0018001800180018001800180018001800180018000000000000000000000'),
    'g': (14, '0000000000000000008007f40e3c1c0c180c18041804180c180c0e1c07fc008c180c0e1807f803e00000000000000000'),
    'h': (14, '00000000000000000c000c000c000c000df00fb80e0c0e0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c00000000000000000000'),
    'i': (14, '000000000000000000c000c00000000000c000c000c000c000c000c000c000c000c000c000c000000000000000000000'),
    'j': (14, '00000000000000c000c00000000000c000c000c000c000c000c000c000c000c000c000c000c000c001c0000000000000'),
    'k': (14, '000000000000000006000600060006000618067006e007c007800700078006c006600630061800000000000000000000'),
    'l': (14, '000000000000000000c000c000c000c000c000c000c000c000c000c000c000c000c000c000c000000000000000000000'),
    'm': (14, '0000000000000000000000001f3e3fff21c301c100810081008100810081008100810000000000000000000000000000'),
    'n': (14, '0000000000000000000000000df00fb80e0c0e0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0000000000000000000000000000'),
    'o': (14, '00000000000000000000000007f00e380c18180c180c180c180c180c0c1807f803e00000000000000000000000000000'),
    'p': (14, '0000000000000000000019f01f381c0c18041806180618061c0e1c0c1f381bf018c01800180018000000000000000000'),
    'q': (14, '0000000000000000000003e4063c0c1c180c18041804180c180c0c1c0f7c07f400840004000400040000000000000000'),
    'r': (14, '000000000000000000000000017001e00180018001800100010001000100010001000000000000000000000000000000'),
    's': (14, '0000000000000000000001e003f003000300038001c0006000300030023003e001c00000000000000000000000000000'),
    't': (14, '0000000000000000008000800080008003e00080008000800080008000800080008000e000e000000000000000000000'),
    'u': (14, '0000000000000000000000000c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0e1c077c03ec0000000000000000000000000000'),
    'v': (14, '000000000000000000000000180c0c180c18063006300360036001c001c0008000800000000000000000000000000000'),
    'w': (14, '0000000000000000000000000081018321c321c633463264162c1e380c380c1808100000000000000000000000000000'),
    'x': (14, '00000000000000000000000006180630037001e001c001c001e00360033006180c180000000000000000000000000000'),
    'y': (14, '0000000000000000180c0c180c18063006300220036003e001c001c00180018003000300030000000000000000000000'),
    'z': (14, '0000000000000000000000000ff00070006000c000c0018003800300060007f00ff00000000000000000000000000000'),
    '缺': (24, '0000000000000c02000c03000c03001803001feff03b0ff01303300303300303303fe330031ffc1b63001b63001b67801b66c01b6cc01ffc7018783c007018006000000000000000'),
    '镜': (24, '0000000000000601000e03000c01000fbff81f8c60380cc0303ffc0f8000061ff00610300610301fdff01fd030061030061ff006cc80078c80070c8c0e388c0460f8000000000000'),
}
_GLYPH_HEIGHT = 24


@dataclass(frozen=True)
class AssemblyOutputs:
    """Paths and metadata generated by assemble_project."""

    output_mp4: Path
    edl_json: Path
    subs_srt: Path
    edl: dict[str, Any]


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _fill_rect(
    buf: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    rgb: tuple[int, int, int],
) -> None:
    cx0 = max(0, min(width, x0))
    cy0 = max(0, min(height, y0))
    cx1 = max(0, min(width, x1))
    cy1 = max(0, min(height, y1))
    if cx0 >= cx1 or cy0 >= cy1:
        return
    row_bytes = bytes(rgb) * (cx1 - cx0)
    stride = width * 3
    for y in range(cy0, cy1):
        offset = y * stride + cx0 * 3
        buf[offset : offset + len(row_bytes)] = row_bytes


def _draw_bitmap_text(
    buf: bytearray,
    img_w: int,
    img_h: int,
    text: str,
    center_x: int,
    top_y: int,
    scale: int,
    rgb: tuple[int, int, int],
) -> None:
    spacing = max(1, scale * 2)
    glyph_specs: list[tuple[int, list[int]]] = []
    for ch in text:
        gw, hex_rows = _BITMAP_GLYPHS.get(ch, _BITMAP_GLYPHS[" "])
        step = len(hex_rows) // _GLYPH_HEIGHT
        rows = [int(hex_rows[i * step : (i + 1) * step], 16) for i in range(_GLYPH_HEIGHT)]
        glyph_specs.append((gw, rows))

    total_w = sum(gw * scale for gw, _ in glyph_specs) + spacing * max(0, len(glyph_specs) - 1)
    cursor_x = center_x - total_w // 2
    for gw, rows in glyph_specs:
        for gy, bits in enumerate(rows):
            if bits == 0:
                continue
            py0 = top_y + gy * scale
            py1 = py0 + scale
            for gx in range(gw):
                if (bits >> (gw - 1 - gx)) & 1:
                    px0 = cursor_x + gx * scale
                    _fill_rect(buf, img_w, img_h, px0, py0, px0 + scale, py1, rgb)
        cursor_x += gw * scale + spacing


def write_missing_shot_card_png(path: Path, shot_id: str, width: int, height: int) -> None:
    """Write a distinct slate-gray placeholder PNG card showing '缺镜 <shot_id>'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bg_rgb = (72, 76, 84)
    panel_rgb = (54, 58, 65)
    border_rgb = (238, 190, 92)
    text_rgb = (248, 249, 250)
    sub_rgb = (196, 202, 212)

    buf = bytearray(bytes(bg_rgb) * (width * height))
    margin_x = max(12, width // 14)
    margin_y = max(12, height // 10)
    border_t = max(2, min(width, height) // 160)

    # Outer diagnostic frame and inner dark slate panel so it never looks like a content still
    _fill_rect(buf, width, height, margin_x, margin_y, width - margin_x, height - margin_y, border_rgb)
    _fill_rect(
        buf,
        width,
        height,
        margin_x + border_t,
        margin_y + border_t,
        width - margin_x - border_t,
        height - margin_y - border_t,
        panel_rgb,
    )

    # Diagonal hazard stripes along top bar inside the diagnostic box
    bar_h = max(6, height // 36)
    inner_x0 = margin_x + border_t
    inner_x1 = width - margin_x - border_t
    inner_y0 = margin_y + border_t
    stripe_w = max(8, width // 40)
    for sx in range(inner_x0, inner_x1, stripe_w * 2):
        _fill_rect(
            buf,
            width,
            height,
            sx,
            inner_y0,
            min(inner_x1, sx + stripe_w),
            inner_y0 + bar_h,
            border_rgb,
        )

    headline = f"缺镜 {shot_id}"
    subtitle = "DRAFT PLACEHOLDER"
    max_text_w = max(80, int((inner_x1 - inner_x0) * 0.82))

    def _raw_text_units(txt: str) -> int:
        widths = [_BITMAP_GLYPHS.get(ch, _BITMAP_GLYPHS[" "])[0] for ch in txt]
        return sum(widths) + 2 * max(0, len(widths) - 1)

    main_scale = max(1, min(width // 220, height // 120, max_text_w // max(1, _raw_text_units(headline))))
    if main_scale < 2 and width >= 320 and height >= 180 and _raw_text_units(headline) * 2 <= max_text_w:
        main_scale = 2
    sub_scale = max(
        1,
        min(
            max(1, main_scale // 2),
            max_text_w // max(1, _raw_text_units(subtitle)),
        ),
    )

    main_h = _GLYPH_HEIGHT * main_scale
    sub_h = _GLYPH_HEIGHT * sub_scale
    gap = max(6, height // 30)
    block_top = (height - (main_h + gap + sub_h)) // 2

    _draw_bitmap_text(buf, width, height, headline, width // 2, block_top, main_scale, text_rgb)
    _draw_bitmap_text(
        buf, width, height, subtitle, width // 2, block_top + main_h + gap, sub_scale, sub_rgb
    )

    stride = width * 3
    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)  # Filter type 0 (None)
        row_start = y * stride
        raw_scanlines.extend(buf[row_start : row_start + stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(bytes(raw_scanlines), level=6)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png_bytes)


def format_srt_timestamp(seconds: float) -> str:
    clamped = max(0.0, seconds)
    total_ms = int(round(clamped * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt_content(entries: list[dict[str, Any]], shots_by_id: dict[str, dict[str, Any]]) -> str:
    blocks: list[str] = []
    cue_index = 1
    for entry in entries:
        shot = shots_by_id[entry["id"]]
        clip_dur = float(entry["duration"])
        tl_start = float(entry["timeline_start"])
        for line in shot.get("dialogue") or []:
            at_rel = float(line["at"])
            end_rel = min(float(line["end"]), clip_dur)
            if at_rel >= clip_dur or end_rel <= at_rel:
                continue
            start_ts = format_srt_timestamp(tl_start + at_rel)
            end_ts = format_srt_timestamp(tl_start + end_rel)
            text = str(line["text"]).strip()
            blocks.append(f"{cue_index}\n{start_ts} --> {end_ts}\n{text}\n")
            cue_index += 1
    return "\n".join(blocks)


def _run_ffmpeg_checked(args: list[str], context: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"{context} failed: {detail}")


def _video_scale_filter(width: int, height: int, fps: int, fit: str) -> str:
    if fit == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )


def _render_segment(
    *,
    seg_path: Path,
    source_path: Path,
    is_still_image: bool,
    in_pt: float,
    seg_dur: float,
    frames: int,
    width: int,
    height: int,
    fps: int,
    fit: str,
    audio_mode: str,
    source_has_audio: bool,
    replace_audio_path: Path | None,
) -> None:
    seg_path.parent.mkdir(parents=True, exist_ok=True)
    vf_scale = _video_scale_filter(width, height, fps, fit)
    fade_d = min(0.01, seg_dur / 2.0)
    fade_out_st = max(0.0, seg_dur - fade_d)

    inputs: list[str] = []
    if is_still_image:
        inputs.extend(["-loop", "1", "-framerate", str(fps), "-i", str(source_path)])
        v_chain = f"[0:v]{vf_scale},trim=start=0:end={seg_dur:.6f},setpts=PTS-STARTPTS[vout]"
    else:
        inputs.extend(["-i", str(source_path)])
        end_pt = in_pt + seg_dur
        v_chain = (
            f"[0:v]trim=start={in_pt:.6f}:end={end_pt:.6f},"
            f"setpts=PTS-STARTPTS,{vf_scale}[vout]"
        )

    if audio_mode == "source" and not is_still_image and source_has_audio:
        end_pt = in_pt + seg_dur
        a_chain = (
            f"[0:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"atrim=start={in_pt:.6f}:end={end_pt:.6f},asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={seg_dur:.6f},atrim=0:{seg_dur:.6f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_d:.6f},afade=t=out:st={fade_out_st:.6f}:d={fade_d:.6f}[aout]"
        )
    elif audio_mode.startswith("replace:") and replace_audio_path is not None:
        inputs.extend(["-i", str(replace_audio_path)])
        a_chain = (
            f"[1:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"atrim=start=0:end={seg_dur:.6f},asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={seg_dur:.6f},atrim=0:{seg_dur:.6f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_d:.6f},afade=t=out:st={fade_out_st:.6f}:d={fade_d:.6f}[aout]"
        )
    else:
        inputs.extend(
            ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        )
        a_chain = (
            f"[1:a]atrim=0:{seg_dur:.6f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=s16:channel_layouts=stereo[aout]"
        )

    filter_complex = f"{v_chain};{a_chain}"
    args = [
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-frames:v",
        str(frames),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(seg_path),
    ]
    _run_ffmpeg_checked(args, f"render segment {seg_path.name}")


def _verify_rendered_output(
    output_mp4: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: int,
    expected_duration: float,
) -> ProbeInfo:
    info = probe_media(output_mp4)
    if not info.has_video:
        raise RuntimeError(f"Output {output_mp4} is missing video stream")
    if not info.has_audio:
        raise RuntimeError(f"Output {output_mp4} is missing audio stream")
    if info.video_codec != "h264":
        raise RuntimeError(f"Expected h264 video codec, got {info.video_codec!r}")
    if info.audio_codec != "aac":
        raise RuntimeError(f"Expected aac audio codec, got {info.audio_codec!r}")
    if info.width != expected_width or info.height != expected_height:
        raise RuntimeError(
            f"Expected resolution {expected_width}x{expected_height}, "
            f"got {info.width}x{info.height}"
        )
    if info.fps is None or abs(info.fps - expected_fps) > 0.1:
        raise RuntimeError(f"Expected fps {expected_fps}, got {info.fps!r}")
    if info.duration is None:
        raise RuntimeError(f"Could not determine duration of {output_mp4}")

    # Video duration must stay within 1 frame (plus AAC packetization tail <= 1024/48000s)
    frame_tol = (1.0 / expected_fps) + (1024.0 / 48000.0) + 1e-3
    if abs(info.duration - expected_duration) > frame_tol:
        raise RuntimeError(
            f"Output duration {info.duration:.4f}s differs from expected "
            f"{expected_duration:.4f}s by more than tolerance ({frame_tol:.4f}s)"
        )

    decode_proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(output_mp4), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if decode_proc.returncode != 0 or decode_proc.stderr.strip():
        detail = decode_proc.stderr.strip() or f"exit code {decode_proc.returncode}"
        raise RuntimeError(f"Full FFmpeg decode check failed for {output_mp4}: {detail}")

    return info


def assemble_project(
    project_dir: Path | str,
    *,
    draft: bool = False,
    shots_spec: str | None = None,
    date_tag: str | None = None,
    repo_root: Path | None = None,
) -> AssemblyOutputs:
    """Validate and assemble shots into output MP4, build/edl.json, and build/subs.srt."""
    proj_path = Path(project_dir).resolve()

    # Step 1: Always run manifest validation before assembly.
    manifest_res = validate_project(proj_path, check_media=False, repo_root=repo_root)
    if not manifest_res.ok:
        joined = "\n".join(f"  - {e}" for e in manifest_res.errors)
        raise ValueError(f"Manifest validation failed:\n{joined}")

    selected_shots = select_shot_range(manifest_res.shots, shots_spec)
    if not selected_shots:
        raise ValueError("No shots selected for assembly")

    selected_ids = {str(s["id"]) for s in selected_shots}

    # Step 2: Mode-specific status & media enforcement.
    if not draft:
        unapproved = [
            f"{s['id']} ({s['status']})" for s in selected_shots if s.get("status") != "approved"
        ]
        if unapproved:
            raise ValueError(
                f"Release mode requires all selected shots to be 'approved'; "
                f"unapproved shots: {', '.join(unapproved)}"
            )
        media_res = validate_project(
            proj_path,
            check_media=True,
            media_shot_ids=selected_ids,
            repo_root=manifest_res.repo_root,
        )
        if not media_res.ok:
            joined = "\n".join(f"  - {e}" for e in media_res.errors)
            raise ValueError(f"Media validation failed:\n{joined}")
    else:
        explicit_sel_ids = {
            str(s["id"]) for s in selected_shots if isinstance(s.get("selected"), dict)
        }
        if explicit_sel_ids:
            media_res = validate_project(
                proj_path,
                check_media=True,
                media_shot_ids=explicit_sel_ids,
                repo_root=manifest_res.repo_root,
            )
            if not media_res.ok:
                joined = "\n".join(f"  - {e}" for e in media_res.errors)
                raise ValueError(f"Media validation failed for selected shots:\n{joined}")

    res_match = RESOLUTION_RE.fullmatch(str(manifest_res.project["resolution"]))
    assert res_match is not None
    target_w = int(res_match.group(1))
    target_h = int(res_match.group(2))
    target_fps = int(manifest_res.project["fps"])
    slug = str(manifest_res.project["slug"])

    build_dir = proj_path / "build"
    segments_dir = build_dir / "segments"
    cards_dir = build_dir / "cards"
    output_dir = proj_path / "output"
    build_dir.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for stale_seg in segments_dir.glob("seg_*.mkv"):
        stale_seg.unlink()

    edl_entries: list[dict[str, Any]] = []
    segment_paths: list[Path] = []
    timeline_cursor = 0.0

    for idx, shot in enumerate(selected_shots):
        shot_id = str(shot["id"])
        sel = shot.get("selected")
        candidates = shot.get("candidates") or []
        seg_path = segments_dir / f"seg_{idx:03d}_{shot_id}.mkv"

        if isinstance(sel, dict):
            cands_by_id = {str(c["id"]): c for c in candidates}
            cand = cands_by_id[str(sel["candidate"])]
            rel_file = str(cand["file"])
            src_path = resolve_confined_path(proj_path, rel_file)
            assert src_path is not None
            info = probe_media(src_path)
            is_still = src_path.suffix.lower() in IMAGE_EXTENSIONS
            in_pt = float(sel["in"])
            out_pt = float(sel["out"])
            raw_dur = out_pt - in_pt
            frames = max(1, int(round(raw_dur * target_fps)))
            if not is_still and info.duration is not None:
                max_avail_frames = max(1, int(math.floor((info.duration - in_pt + 1e-4) * target_fps)))
                frames = min(frames, max_avail_frames)
            seg_dur = frames / float(target_fps)

            audio_mode = str(sel.get("audio", "source"))
            fit = "crop" if (sel.get("crop") is True or sel.get("fit") == "crop") else "pad"
            rep_path = (
                resolve_confined_path(proj_path, audio_mode.split(":", 1)[1])
                if audio_mode.startswith("replace:")
                else None
            )

            _render_segment(
                seg_path=seg_path,
                source_path=src_path,
                is_still_image=is_still,
                in_pt=in_pt,
                seg_dur=seg_dur,
                frames=frames,
                width=target_w,
                height=target_h,
                fps=target_fps,
                fit=fit,
                audio_mode=audio_mode,
                source_has_audio=info.has_audio,
                replace_audio_path=rep_path,
            )
            entry_mode = "selected"
            edl_source: str | None = rel_file
            edl_cand_id: str | None = str(cand["id"])
            edl_out = round(in_pt + seg_dur, 6)

        elif draft and candidates:
            cand = candidates[0]
            rel_file = str(cand["file"])
            src_path = resolve_confined_path(proj_path, rel_file)
            if src_path is None or not src_path.is_file():
                raise ValueError(
                    f"Draft candidate file does not exist for shot {shot_id!r}: {rel_file}"
                )
            ext = src_path.suffix.lower()
            if shot.get("kind") == "performance" and ext not in VIDEO_EXTENSIONS:
                raise ValueError(
                    f"Draft candidate for performance shot {shot_id!r} must be a video "
                    f"({sorted(VIDEO_EXTENSIONS)}), got {ext!r}"
                )
            actual_sha = sha256_file(src_path)
            if actual_sha != cand["sha256"]:
                raise ValueError(
                    f"Draft candidate sha256 mismatch for shot {shot_id!r} ({rel_file}): "
                    f"expected {cand['sha256']}, got {actual_sha}"
                )
            info = probe_media(src_path)
            if not info.has_video:
                raise ValueError(f"Draft candidate {rel_file} has no video/image stream")
            is_still = src_path.suffix.lower() in IMAGE_EXTENSIONS
            in_pt = 0.0
            if is_still:
                raw_dur = float(shot["target_duration"])
                frames = max(1, int(round(raw_dur * target_fps)))
            else:
                if info.duration is None or info.duration <= 0:
                    raise ValueError(f"Could not determine duration of {rel_file}")
                frames = max(1, int(math.floor((info.duration + 1e-4) * target_fps)))
            seg_dur = frames / float(target_fps)
            audio_mode = "source"
            fit = "pad"

            _render_segment(
                seg_path=seg_path,
                source_path=src_path,
                is_still_image=is_still,
                in_pt=in_pt,
                seg_dur=seg_dur,
                frames=frames,
                width=target_w,
                height=target_h,
                fps=target_fps,
                fit=fit,
                audio_mode=audio_mode,
                source_has_audio=info.has_audio,
                replace_audio_path=None,
            )
            entry_mode = "draft_candidate"
            edl_source = rel_file
            edl_cand_id = str(cand["id"])
            edl_out = round(seg_dur, 6)

        elif draft:
            card_path = cards_dir / f"missing-{shot_id}.png"
            write_missing_shot_card_png(card_path, shot_id, target_w, target_h)
            in_pt = 0.0
            raw_dur = float(shot["target_duration"])
            frames = max(1, int(round(raw_dur * target_fps)))
            seg_dur = frames / float(target_fps)
            audio_mode = "mute"
            fit = "pad"

            _render_segment(
                seg_path=seg_path,
                source_path=card_path,
                is_still_image=True,
                in_pt=0.0,
                seg_dur=seg_dur,
                frames=frames,
                width=target_w,
                height=target_h,
                fps=target_fps,
                fit=fit,
                audio_mode="mute",
                source_has_audio=False,
                replace_audio_path=None,
            )
            entry_mode = "placeholder"
            edl_source = str(card_path.relative_to(proj_path))
            edl_cand_id = None
            edl_out = round(seg_dur, 6)

        else:
            raise AssertionError(f"Unreachable state for shot {shot_id!r}")

        segment_paths.append(seg_path)
        tl_start = round(timeline_cursor, 6)
        timeline_cursor += seg_dur
        tl_end = round(timeline_cursor, 6)
        edl_entries.append(
            {
                "id": shot_id,
                "status": shot["status"],
                "mode": entry_mode,
                "candidate": edl_cand_id,
                "source_file": edl_source,
                "in": round(in_pt, 6),
                "out": edl_out,
                "duration": round(seg_dur, 6),
                "frames": frames,
                "timeline_start": tl_start,
                "timeline_end": tl_end,
                "audio": audio_mode,
                "fit": fit,
            }
        )

    # Step 3: Concatenate lossless-audio MKV segments into final H.264 + AAC MP4.
    concat_list_path = build_dir / "concat.txt"
    concat_lines: list[str] = []
    for seg in segment_paths:
        escaped = str(seg.resolve()).replace("'", "'\\''")
        concat_lines.append(f"file '{escaped}'\n")
    concat_list_path.write_text("".join(concat_lines), encoding="utf-8")

    if shots_spec:
        shots_label = shots_spec.strip()
    elif len(selected_shots) == 1:
        shots_label = str(selected_shots[0]["id"])
    else:
        shots_label = f"{selected_shots[0]['id']}-{selected_shots[-1]['id']}"

    stamp = date_tag or datetime.now().strftime("%Y%m%d")
    suffix = "-draft" if draft else ""
    output_mp4 = output_dir / f"{slug}-{shots_label}-{stamp}{suffix}.mp4"

    _run_ffmpeg_checked(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ],
        f"mux final output {output_mp4.name}",
    )

    # Step 4: Verify output specs, duration, and full FFmpeg decode before declaring success.
    expected_total_dur = round(timeline_cursor, 6)
    _verify_rendered_output(
        output_mp4,
        expected_width=target_w,
        expected_height=target_h,
        expected_fps=target_fps,
        expected_duration=expected_total_dur,
    )

    # Step 5: Write build/edl.json and build/subs.srt.
    shots_by_id = {str(s["id"]): s for s in selected_shots}
    srt_text = build_srt_content(edl_entries, shots_by_id)
    subs_srt = build_dir / "subs.srt"
    subs_srt.write_text(srt_text, encoding="utf-8")

    edl_payload = {
        "schema_version": 1,
        "slug": slug,
        "mode": "draft" if draft else "release",
        "fps": target_fps,
        "resolution": f"{target_w}x{target_h}",
        "shots_range": shots_label,
        "output_file": str(output_mp4.relative_to(proj_path)),
        "output_sha256": sha256_file(output_mp4),
        "total_duration": expected_total_dur,
        "total_frames": sum(int(e["frames"]) for e in edl_entries),
        "shots": edl_entries,
    }
    edl_json = build_dir / "edl.json"
    edl_json.write_text(
        json.dumps(edl_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return AssemblyOutputs(
        output_mp4=output_mp4,
        edl_json=edl_json,
        subs_srt=subs_srt,
        edl=edl_payload,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble validated shots into a draft or release MP4."
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="Path to project directory (e.g. projects/zaideng)",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Allow non-approved shots using first candidate or '缺镜 <id>' placeholder cards.",
    )
    parser.add_argument(
        "--shots",
        type=str,
        default=None,
        help="Optional shot range (e.g. 15a-15d) or single shot id.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Optional YYYYMMDD override for deterministic output filenames.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        out = assemble_project(
            args.project_dir,
            draft=args.draft,
            shots_spec=args.shots,
            date_tag=args.date,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK ({out.edl['mode']}): {out.output_mp4} "
        f"({out.edl['total_duration']:.3f}s, {len(out.edl['shots'])} shots)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
