# Max Edge video pipeline

1. `host-max-edge.jpg`: clean reference frame of Max (extracted from the Oct 25 clip, caption painted out) so every day's clip keeps the same look.
2. `script-<date>.json`: the day's four ~15 s segment lines (numbers spelled out), banners, style prompt and end card.
3. Generate each segment with GenerateVideo (reference image = `host-max-edge.jpg`, prompt = `style` + segment `action` + `He says: "<line>"`, 9:16, ~15 s) and save as `video/work/<date>/seg1.mp4` … `seg4.mp4` (work/ is git-ignored).
4. `python3 video/assemble.py <date>` → STT check (faster-whisper; fails if any segment matches the script < 0.85), dead-air trim, alternating zoom, teal banners + whoosh at joins, burned captions, quiet music bed, end card. Writes `video/max-<date>.mp4`, `clips/max-<date>.mp4` (compressed, picked up by build.py) and `clips/max-<date>.jpg`.
Deps: ffmpeg (libass), `pip install --break-system-packages faster-whisper`.
5. **Fallback when AI video generation fails** (no `seg*.mp4` in `video/work/<date>/`, e.g. Nov 1, 2026): `python3 video/tts_segments.py <date>` makes seg1-4 from the host still + an offline Piper TTS voice (`en_US-ryan-high`, free, no account) with a live teal waveform and a "MAX EDGE · AI HOST" label, then run `assemble.py` as usual. For TTS segments (`tts<N>.wav` present) captions use the script words verbatim, timed from STT. Never ship a day without a clip just because video generation is down.
Deps for the fallback: `pip install --break-system-packages piper-tts` (voice auto-downloads to ~/.cache/piper).
