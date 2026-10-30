"""Upload an MP4 to the owner's TikTok inbox as a draft (Content Posting API, upload flow).

Skips cleanly (status "skipped") when TikTok secrets are missing.
Docs: developers.tiktok.com/doc/content-posting-api-reference-upload-video
"""
import os
import sys
import time
from pathlib import Path

import requests

API = "https://open.tiktokapis.com/v2"
SINGLE_CHUNK_MAX = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024
SECRETS = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")


class PublishError(RuntimeError):
    pass


def summary(md: str):
    """Append markdown to the GitHub Actions job summary (no-op locally)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def mask(value: str):
    if os.environ.get("GITHUB_ACTIONS") and value:
        print(f"::add-mask::{value}")


def refresh_access_token() -> str:
    old = os.environ["TIKTOK_REFRESH_TOKEN"]
    r = requests.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": old,
    })
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise PublishError(f"token refresh failed: {data.get('error')} {data.get('error_description')}")
    mask(token)
    new = data.get("refresh_token")
    if new and new != old:
        mask(new)
        print("WARNING: TikTok returned a NEW refresh token. Update the TIKTOK_REFRESH_TOKEN secret "
              "(run tools/get_tiktok_token.py again).")
        summary("## ⚠️ TikTok refresh token changed\nTikTok rotated the refresh token. The old secret may stop "
                "working. Run `python tools/get_tiktok_token.py` locally and update the "
                "`TIKTOK_REFRESH_TOKEN` repository secret.\n")
    return token


def _json_post(url, token, body):
    r = requests.post(url, json=body, timeout=30, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    data = r.json()
    err = data.get("error", {})
    if err.get("code") != "ok":
        raise PublishError(f"{url.rsplit('/v2/', 1)[-1]} -> {err.get('code')}: {err.get('message')}")
    return data["data"]


def upload(video: Path) -> str:
    """Returns the final status string, or 'skipped' if secrets are missing."""
    missing = [k for k in SECRETS if not os.environ.get(k)]
    if missing:
        print(f"[publish] skipping TikTok upload, missing: {', '.join(missing)}")
        return "skipped"
    video = Path(video)
    size = video.stat().st_size
    if size <= SINGLE_CHUNK_MAX:
        chunk_size, count = size, 1
    else:
        chunk_size, count = CHUNK, size // CHUNK  # last chunk absorbs the remainder

    token = refresh_access_token()
    init = _json_post(f"{API}/post/publish/inbox/video/init/", token, {"source_info": {
        "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}})
    publish_id, upload_url = init["publish_id"], init["upload_url"]
    print(f"[publish] publish_id={publish_id}, uploading {size} bytes in {count} chunk(s)")

    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk_size
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(upload_url, data=body, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise PublishError(f"chunk {i + 1}/{count} upload failed: HTTP {r.status_code} {r.text[:200]}")

    deadline = time.time() + 120
    status = "PROCESSING_UPLOAD"
    while time.time() < deadline:
        data = _json_post(f"{API}/post/publish/status/fetch/", token, {"publish_id": publish_id})
        status = data.get("status", "")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            print(f"[publish] done: {status}")
            return status
        if status == "FAILED":
            raise PublishError(f"TikTok processing failed: {data.get('fail_reason')}")
        time.sleep(5)
    print(f"[publish] still {status} after 2 min; TikTok will finish it in the background")
    return status


if __name__ == "__main__":
    print(upload(Path(sys.argv[1])))
