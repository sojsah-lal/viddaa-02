# TikTok Autopilot

One code-rendered vertical video per day, uploaded to your TikTok inbox as a draft. You open
TikTok, add the caption, switch on the AI-generated label, and tap Post. Runs free on GitHub
Actions: no GPU, no paid APIs, no copyrighted music.

```
plan (LLM or preset) -> validate -> render (pygame + FFmpeg) -> QA (ffprobe) -> TikTok inbox -> history.json
```

## Run locally

Needs Python 3.12 and FFmpeg (`winget install Gyan.FFmpeg`, then open a new terminal).

```bash
pip install -r requirements.txt
python run.py --no-publish
```

Output lands in `output/`: `YYYY-MM-DD_<format>.mp4`, `config.json`, `caption.txt`.

| Flag | Effect |
|---|---|
| `--no-publish` | render + QA only |
| `--format escape_rings` / `color_race` | force a format |
| `--config presets/color_race_1.json` | skip planning, render this config |
| `--seed 123` | force the seed (same config + seed = same video) |

Render a single config without the rest of the pipeline: `python -m engine.render presets/escape_rings_1.json output/test.mp4`.
QA any file: `python -m qa.check output/test.mp4`.

## Formats

- **escape_rings**: "Can the ball escape all N rings?" Rotating rings with gaps; each escape shatters a ring.
- **color_race**: "Which color wins?" A Plinko race down a scrolling peg board, first across the line wins.

Each format picks among derived seeds so the ending lands 13–36 s in, so videos run 15–45 s.

## GitHub setup

1. Push this folder to a **private** repo.
2. Settings → Secrets and variables → Actions:

| Name | Kind | Needed? |
|---|---|---|
| `TIKTOK_CLIENT_KEY` | secret | for upload |
| `TIKTOK_CLIENT_SECRET` | secret | for upload |
| `TIKTOK_REFRESH_TOKEN` | secret | for upload (from `tools/get_tiktok_token.py`) |
| `GEMINI_API_KEY` | secret | optional: AI-written hooks/captions |
| `GEMINI_MODEL` | variable | optional, default `gemini-3.5-flash-lite` |
| `LLM_PROVIDER` | variable | optional, `claude` to use Claude Code instead of Gemini |
| `CLAUDE_CODE_OAUTH_TOKEN` | secret | only with `LLM_PROVIDER=claude` (`claude setup-token`) |

With no secrets at all it still renders daily and keeps the MP4 as a workflow artifact (14 days).

3. Actions → daily-video → Run workflow to test. It also runs every day at 18:00 Bangkok time.

## TikTok app (one time)

1. Create an app at developers.tiktok.com, platform **Desktop**, add products **Login Kit** and
   **Content Posting API** (upload / draft only; Direct Post needs an audit).
2. Scopes: `user.info.basic`, `video.upload`. Redirect URI: `http://localhost:8080/callback/`.
3. While the app is unaudited, add your TikTok account as a target/test user in the app's Sandbox.
4. Run `python tools/get_tiktok_token.py`, log in, and save the printed refresh token as
   `TIKTOK_REFRESH_TOKEN`. It lasts about a year; the job summary warns you if TikTok rotates it.

TikTok allows at most 5 pending inbox drafts per 24 h, so post or delete drafts regularly.
