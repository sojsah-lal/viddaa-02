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

1. Push this folder to a GitHub repo (public is fine: secrets stay encrypted). Settings → Pages → `main` / `docs` hosts the Terms and Privacy pages TikTok asks for.
2. Settings → Secrets and variables → Actions:

| Name | Kind | Needed? |
|---|---|---|
| `TIKTOK_CLIENT_KEY` | secret | for upload |
| `TIKTOK_CLIENT_SECRET` | secret | for upload |
| `TIKTOK_REFRESH_TOKEN` | secret | for upload; the `tiktok-login` workflow sets it for you |
| `GH_PAT` | secret | lets workflows save `TIKTOK_REFRESH_TOKEN` (fine-grained token, this repo, Secrets: read/write) |
| `GEMINI_API_KEY` | secret | optional: AI-written hooks/captions |
| `GEMINI_MODEL` | variable | optional, default `gemini-3.5-flash-lite` |
| `LLM_PROVIDER` | variable | optional, `claude` to use Claude Code instead of Gemini |
| `CLAUDE_CODE_OAUTH_TOKEN` | secret | only with `LLM_PROVIDER=claude` (`claude setup-token`) |

With no secrets at all it still renders daily and keeps the MP4 as a workflow artifact (14 days).

3. Actions → daily-video → Run workflow to test. It also runs every day at 18:00 Bangkok time.

## TikTok app (one time)

Everything runs in the browser; no local setup needed.

1. Create an app at developers.tiktok.com, platform **Web**, add products **Login Kit** and
   **Content Posting API** (upload / draft only; Direct Post needs an audit). Switch to **Sandbox**
   and add your TikTok account as a target user; no review is needed for your own account.
2. Scopes: `user.info.basic`, `video.upload`. Web redirect URI:
   `https://sojsah-lal.github.io/viddaa-02/callback.html` (set repo variable `TIKTOK_REDIRECT_URI` if yours differs).
3. Add secrets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `GH_PAT`.
4. Open `https://sojsah-lal.github.io/viddaa-02/login.html`, paste the client key, approve in TikTok, copy the code.
5. Actions → tiktok-login → Run workflow → paste the code. It saves `TIKTOK_REFRESH_TOKEN`.

The refresh token lasts about a year; if TikTok rotates it, the daily job saves the new one via `GH_PAT`.
Offline alternative: `python tools/get_tiktok_token.py` (Desktop app, `http://localhost:8080/callback/`)
or `--web` (paste the code into the terminal).

TikTok allows at most 5 pending inbox drafts per 24 h, so post or delete drafts regularly.
