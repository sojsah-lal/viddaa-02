"""One-time local helper: log in to TikTok in the browser and print a refresh token.

Usage (from the repo root):
    python tools/get_tiktok_token.py          # Desktop app: redirect http://localhost:8080/callback/
    python tools/get_tiktok_token.py --web    # Web app: redirect WEB_REDIRECT (https page), paste the code back
    python tools/get_tiktok_token.py --web https://example.com/callback.html
It reads TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET from the environment or asks for them.
The redirect URI must be listed exactly in your TikTok app (Login Kit -> Redirect URI).
Desktop apps need PKCE; TikTok wants the challenge as hex(SHA256(verifier)). Web apps don't.
"""
import argparse
import getpass
import hashlib
import http.server
import os
import secrets
import string
import sys
import urllib.parse
import webbrowser

import requests

PORT = 8080
DESKTOP_REDIRECT = f"http://localhost:{PORT}/callback/"
WEB_REDIRECT = "https://sojsah-lal.github.io/viddaa-02/callback.html"
SCOPES = "user.info.basic,video.upload"


def wait_for_local_callback() -> dict:
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab and go back to the terminal.</h2>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()
    return result


def parse_pasted(text: str) -> dict:
    """Accepts the full URL TikTok redirected to, or just the code."""
    text = text.strip()
    if "code=" in text or "error=" in text:
        query = urllib.parse.urlparse(text).query or text.split("?", 1)[-1]
        return {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
    return {"code": text}


def main():
    ap = argparse.ArgumentParser(description="Get a TikTok refresh token")
    ap.add_argument("--web", nargs="?", const=WEB_REDIRECT, metavar="REDIRECT_URI",
                    help=f"Web app flow (default redirect {WEB_REDIRECT})")
    args = ap.parse_args()
    redirect = args.web or DESKTOP_REDIRECT

    key = os.environ.get("TIKTOK_CLIENT_KEY") or input("TikTok client key: ").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET") or getpass.getpass("TikTok client secret (hidden): ").strip()
    state = secrets.token_urlsafe(16)
    params = {"client_key": key, "response_type": "code", "scope": SCOPES, "redirect_uri": redirect,
              "state": state}
    verifier = None
    if not args.web:
        verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(64))
        params.update(code_challenge=hashlib.sha256(verifier.encode()).hexdigest(), code_challenge_method="S256")
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)

    print(f"Opening TikTok login in your browser...\nIf it does not open, visit:\n{url}\n")
    webbrowser.open(url)
    if args.web:
        print(f"After you approve, TikTok sends you to {redirect}")
        result = parse_pasted(input("Paste the code shown there (or the whole address-bar URL), then Enter:\n> "))
    else:
        result = wait_for_local_callback()

    if result.get("error"):
        sys.exit(f"TikTok returned an error: {result.get('error')} {result.get('error_description', '')}")
    if "state" in result and result["state"] != state:
        sys.exit("State mismatch; aborting (possible CSRF). Try again.")

    data = {"client_key": key, "client_secret": secret, "code": result["code"],
            "grant_type": "authorization_code", "redirect_uri": redirect}
    if verifier:
        data["code_verifier"] = verifier
    resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data=data).json()
    if "refresh_token" not in resp:
        sys.exit(f"Token exchange failed: {resp}")
    print("\nSuccess. Scopes granted:", resp.get("scope"))
    print("Refresh token expires in about", int(resp.get("refresh_expires_in", 0)) // 86400, "days.")
    print("\nSave this as the GitHub secret TIKTOK_REFRESH_TOKEN (shown once):\n")
    print(resp["refresh_token"])


if __name__ == "__main__":
    main()
