# Max Edge video pipeline

1. `host-max-edge.jpg`: clean reference frame of Max (extracted from the Oct 25 clip, caption painted out) so every day's clip keeps the same look.
2. `script-<date>.json`: the day's four ~15 s segment lines (numbers spelled out), banners, style prompt and end card.
3. Generate each segment with GenerateVideo (reference image = `host-max-edge.jpg`, prompt = `style` + segment `action` + `He says: "<line>"`, 9:16, ~15 s) and save as `video/work/<date>/seg1.mp4` … `seg4.mp4` (work/ is git-ignored).
4. `python3 video/assemble.py <date>` → STT check (faster-whisper; fails if any segment matches the script < 0.85), dead-air trim, alternating zoom, teal banners + whoosh at joins, burned captions, quiet music bed, end card. Writes `video/max-<date>.mp4`, `clips/max-<date>.mp4` (compressed, picked up by build.py) and `clips/max-<date>.jpg`.
Deps: ffmpeg (libass), `pip install --break-system-packages faster-whisper`.
