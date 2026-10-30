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
        print(f"::warning::could not save {name}: {out.stderr.strip()[:200]}")
        return False
    return True


def fail(msg: str):
    """Exit with an ::error:: annotation, which shows on the run page even without log access."""
    print(f"::error::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg)
    sys.exit(1)


if __name__ == "__main__":
    # Check everything before spending the one-time code.
    missing = [k for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "GH_PAT") if not os.environ.get(k)]
    if missing:
        fail(f"Missing repo secret(s): {', '.join(missing)}. Add them in Settings > Secrets and variables > "
             "Actions, then log in again for a new code.")
    code = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not code:
        fail("No code given. Paste the code from the Vidda login page.")
    try:
        tokens = exchange_code(code)
    except RuntimeError as e:
        fail(f"TikTok rejected the code ({e}). Codes expire after a few minutes and work once: "
             "log in again on login.html and run this workflow right away.")
    print("[auth] TikTok login OK, scopes:", tokens.get("scope"))
    if not save_secret("TIKTOK_REFRESH_TOKEN", tokens["refresh_token"]):
        fail("TikTok login worked but saving TIKTOK_REFRESH_TOKEN failed: GH_PAT needs access to this repo "
             "with permission Secrets: Read and write.")
    print("[auth] saved TIKTOK_REFRESH_TOKEN. Daily uploads are now on.")
