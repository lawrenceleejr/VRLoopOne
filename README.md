# Loop One

WebXR player for Meta Quest: each video loops until you push the stick right, then the next one loops. Videos play from the headset’s own storage.

## Deploy (once)

1. Push this folder to a new GitHub repo on `main`.
2. Repo Settings → Pages → Source: **GitHub Actions**. The included workflow publishes `site/`.
3. On the Quest, open `https://<you>.github.io/<repo>/` in Meta Quest Browser while online and bookmark it. After that first visit it loads offline.

## Use

- **Add videos** → Internal storage → Download (where Drive downloads land). Long-press to multi-select. Re-add each time the page reloads; browsers can’t keep file access.
- Order is by filename (`01_…`, `02_…`). Format is guessed from tags like `_180`, `_360`, `_LR`/`_SBS`, `_TB`/`_OU`, else from aspect ratio; change it per video and it’s remembered by filename.
- In VR: stick right or A/X = next, stick left = start the video over, or the previous video if within its first 3 s (wraps), trigger = pause, B/Y = leave VR.
- The headset's refresh rate is matched to each video's frame rate (90 Hz for 30 fps, 120 Hz for 60 fps, 72 Hz for 24 fps) so every frame is held for the same time. If a video still stutters, it is likely more than the headset can decode; a lower resolution or bitrate copy will help.
- If a video shows black, switch Renderer to WebGL. If a file won’t load at all, the headset browser can’t decode that codec/resolution.

## Test

`python3 test/run_test.py` — headless Chromium with a mocked WebXR runtime (needs `ffmpeg`, `playwright`).
