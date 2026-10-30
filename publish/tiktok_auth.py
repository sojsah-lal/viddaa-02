"""TikTok OAuth helpers shared by the cloud login workflow and the daily upload.

`python -m publish.tiktok_auth CODE` exchanges a one-time login code (from docs/callback.html)
for tokens and stores the refresh token as the TIKTOK_REFRESH_TOKEN repo secret.
"""
import os
import subprocess
import sys

import requests

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
WEB_REDIRECT = os.environ.get("TIKTOK_REDIRECT_URI") or "https://sojsah-lal.github.io/viddaa-02/callback.html"


def mask(value: str):
    if os.environ.get("GITHUB_ACTIONS") and value:
        print(f"::add-mask::{value}")


def exchange_code(code: str, redirect: str = WEB_REDIRECT, verifier: str = None) -> dict:
    data = {"client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
            "code": code.strip(), "grant_type": "authorization_code", "redirect_uri": redirect}
    if verifier:
        data["code_verifier"] = verifier
    resp = requests.post(TOKEN_URL, data=data, timeout=30).json()
    if "refresh_token" not in resp:
        raise RuntimeError(f"token exchange failed: {resp.get('error')} {resp.get('error_description')}")
    mask(resp.get("access_token"))
    mask(resp["refresh_token"])
    return resp


def save_secret(name: str, value: str) -> bool:
    """Store a repo secret with the gh CLI. Needs GH_PAT (fine-grained, Secrets: read/write) and GITHUB_REPOSITORY."""
    pat, repo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    if not (pat and repo):
        return False
    out = subprocess.run(["gh", "secret", "set", name, "--repo", repo], input=value, text=True,
                         capture_output=True, env={**os.environ, "GH_TOKEN": pat})
    if out.returncode != 0:
        print(f"[auth] could not save {name}: {out.stderr.strip()[:200]}")
        return False
    return True


if __name__ == "__main__":
    tokens = exchange_code(sys.argv[1])
    print("[auth] TikTok login OK, scopes:", tokens.get("scope"))
    if save_secret("TIKTOK_REFRESH_TOKEN", tokens["refresh_token"]):
        print("[auth] saved TIKTOK_REFRESH_TOKEN. Daily uploads are now on.")
    else:
        sys.exit("[auth] could not save the secret: add a GH_PAT secret (fine-grained token, "
                 "this repo only, permission Secrets: Read and write) and run again with a new code.")
