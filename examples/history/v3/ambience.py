"""Build subtle synthetic location sound for the review cut."""
import wave
import numpy as np

rate = 24000
rng = np.random.default_rng(2717)
track = np.zeros(rate * 180, dtype=np.float32)

def wash(start, stop, level, swell):
    count = int((stop - start) * rate)
    time = np.arange(count) / rate
    anchors = rng.normal(0, 1, count // 12 + 2)
    noise = np.interp(np.arange(count), np.arange(len(anchors)) * 12, anchors)
    edge = np.clip(np.minimum(time, stop - start - time) / 1.3, 0, 1)
    shape = 0.65 + 0.35 * np.sin(2 * np.pi * swell * time)
    pos = int(start * rate)
    track[pos:pos + count] += level * noise * edge * shape

def tap(at, pitch, level, decay):
    time = np.arange(int(rate * 0.75)) / rate
    hit = level * np.exp(-time * decay) * np.sin(2 * np.pi * pitch * time)
    hit *= np.minimum(time / 0.006, 1)
    pos = int(at * rate)
    track[pos:pos + len(time)] += hit

wash(4, 22, .022, .36)
wash(37, 58, .017, .46)
wash(90, 106, .025, .88)
wash(138, 148, .019, .25)
wash(163, 178, .015, .22)
tap(8.4, 710, .095, 22)
tap(24.1, 1060, .035, 24)
tap(112.5, 1390, .11, 20)
tap(112.54, 1720, .058, 25)
with wave.open("assets/ambience.wav", "wb") as writer:
    writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    writer.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
