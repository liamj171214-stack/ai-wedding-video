"""Render a 180-second review cut from shots with explicit durations."""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path("assets")
WORK = Path("work")
WORK.mkdir(exist_ok=True)
FONT = "/System/Library/Fonts/Supplemental/Songti.ttc"

def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *map(str, args)], check=True)

def normalize(path, target, duration, caption):
    is_video = path.suffix == ".mp4"
    fit = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
    if is_video:
        filters = fit + f",fps=24,tpad=stop_mode=clone:stop_duration={duration}"
    else:
        count = duration * 24
        filters = (
            "scale=2496:1404:force_original_aspect_ratio=increase,crop=2496:1404,"
            f"zoompan=z='1.015+0.055*on/{count}':x='iw/2-iw/zoom/2':"
            f"y='ih/2-ih/zoom/2':d={count}:s=1920x1080:fps=24"
        )
    filters += ",setsar=1"
    start = {"meet.mp4": 1, "conflict.mp4": 2}.get(path.name)
    args = ["-ss", str(start), "-i", path] if start else ["-i", path]
    tail = ["-vf", filters]
    if caption:
        card = Image.new("RGBA", (1920, 1080))
        draw = ImageDraw.Draw(card)
        draw.rectangle((0, 0, 1920, 1080), fill=(12, 8, 7, 97))
        title, subtitle = caption
        draw.text((960, 488), title, font=ImageFont.truetype(FONT, 84), anchor="mm", fill="#fff0d7")
        draw.text((960, 594), subtitle, font=ImageFont.truetype(FONT, 34), anchor="mm", fill="#f8dfbc")
        overlay = target.with_suffix(".png")
        card.save(overlay)
        args.extend(["-i", overlay])
        tail = ["-filter_complex", f"[0:v]{filters}[b];[b][1:v]overlay"]
    ff(*args, *tail, "-t", duration, "-an", "-c:v", "libx264", "-preset", "ultrafast",
       "-crf", 19, "-pix_fmt", "yuv420p", target)

first_meeting = (
    [("palace.jpg", 4), ("meet.mp4", 9), ("story-2.png", 4)]
    if (ASSETS / "meet.mp4").is_file()
    else [("palace.jpg", 4), ("story-1.png", 7), ("story-2.png", 6)]
)
conflict = (
    [("story-4.png", 5), ("empty-chair.png", 3), ("conflict.mp4", 8), ("story-6.png", 9), ("cups.png", 8)]
    if (ASSETS / "conflict.mp4").is_file()
    else [("story-4.png", 7), ("empty-chair.png", 4), ("story-5.png", 8), ("story-6.png", 8), ("cups.png", 6)]
)
growing_up = (
    [("child-1.png", 5), ("child-motion.mp4", 10), ("child-4.png", 5),
     ("child-2.png", 6), ("child-6.png", 6)]
    if (ASSETS / "child-motion.mp4").is_file()
    else [("child-1.png", 7), ("child-2.png", 9), ("child-3.png", 5),
          ("child-4.png", 5), ("child-6.png", 6)]
)
wedding = (
    [("vow-start.png", 4), ("vow-motion.mp4", 10), ("vow-end.png", 5)]
    if (ASSETS / "vow-motion.mp4").is_file()
    else [("vow.png", 10), ("letter.png", 4), ("vow.png", 5)]
)
romance = (
    [("story-3.png", 4), ("romance.mp4", 10), ("cups.png", 3)]
    if (ASSETS / "romance.mp4").is_file()
    else [("story-3.png", 8), ("story-2.png", 4), ("story-3.png", 5)]
)
letter = (
    [("wall.jpg", 3), ("write-letter.mp4", 10), ("letter.png", 4)]
    if (ASSETS / "write-letter.mp4").is_file()
    else [("wall.jpg", 4), ("red.png", 5), ("red-detail.png", 3), ("letter.png", 5)]
)
shots = [
    ("letter.png", 8, ("把明天寄给你", "A LETTER TO TOMORROW")),
    *growing_up,
    *first_meeting,
    *romance,
    *letter,
    *conflict,
    ("beach-chase.mp4", 15),
    ("shore.jpg", 4), ("letter.png", 4), ("chapel.jpg", 4),
    *wedding,
    ("chapel.jpg", 5),
    ("letter.png", 5, ("明天见。", "虚构婚礼故事 · 样片素材见制作记录")),
]
assert sum(shot[1] for shot in shots) == 180
for index, (name, seconds, *caption) in enumerate(shots):
    normalize(ASSETS / name, WORK / f"shot-{index:02}.mp4", seconds, caption[0] if caption else None)
    print(f"{index + 1}/{len(shots)} {name}", flush=True)
(WORK / "concat.txt").write_text(
    "".join(f"file 'shot-{i:02}.mp4'\n" for i in range(len(shots))))
ff("-f", "concat", "-safe", 0, "-i", WORK / "concat.txt", "-c", "copy", WORK / "picture.mp4")

args = ["-i", WORK / "picture.mp4", "-stream_loop", "-1", "-i", ASSETS / "music.mp3",
        "-i", ASSETS / "beach-chase.mp4", "-i", ASSETS / "ambience.wav"]
filters = [
    "[1:a]atrim=duration=180,volume='if(between(t,9,23)+between(t,44,59)+between(t,93,111)+between(t,124,139)+between(t,155,163),0.13,0.35)':eval=frame,afade=d=2,afade=t=out:st=174:d=6[m]",
    "[2:a]atrim=duration=15,asetpts=PTS-STARTPTS,volume=0.72,afade=d=0.35,"
    "afade=t=out:st=13:d=2,adelay=124000:all=1[b]",
]
filters.append("[3:a]volume=0.85[e]")
labels = ["[m]", "[b]", "[e]"]
for index, start in enumerate([9, 44, 93, 155], start=1):
    path = ASSETS / f"voice-{index}.mp3"
    if path.is_file():
        n = len(labels) + 1
        args.extend(["-i", path])
        filters.append(f"[{n}:a]volume=1.85,adelay={start * 1000}:all=1[a{index}]")
        labels.append(f"[a{index}]")
filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.9[a]")
ff(*args, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-t", 180,
   "-c:v", "copy", "-c:a", "aac", "-ar", 48000, "-ac", 2, "-b:a", "192k",
   "-movflags", "+faststart", "letter-to-tomorrow-review.mp4")
