"""One-time local helper: log in to TikTok in the browser and print a refresh token.

Usage (from the repo root):
    python tools/get_tiktok_token.py
It reads TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET from the environment or asks for them.
Your TikTok app must list this exact redirect URI: http://localhost:8080/callback/
Desktop apps need PKCE; TikTok wants the challenge as hex(SHA256(verifier)).
"""
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
REDIRECT = f"http://localhost:{PORT}/callback/"
SCOPES = "user.info.basic,video.upload"


def main():
    key = os.environ.get("TIKTOK_CLIENT_KEY") or input("TikTok client key: ").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET") or getpass.getpass("TikTok client secret (hidden): ").strip()
    state = secrets.token_urlsafe(16)
    verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(64))
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "response_type": "code", "scope": SCOPES, "redirect_uri": REDIRECT,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})

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
    print(f"Opening TikTok login in your browser...\nIf it does not open, visit:\n{url}\n")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()

    if result.get("error"):
        sys.exit(f"TikTok returned an error: {result.get('error')} {result.get('error_description', '')}")
    if result.get("state") != state:
        sys.exit("State mismatch; aborting (possible CSRF). Try again.")

    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": key, "client_secret": secret, "code": result["code"],
        "grant_type": "authorization_code", "redirect_uri": REDIRECT, "code_verifier": verifier})
    data = r.json()
    if "refresh_token" not in data:
        sys.exit(f"Token exchange failed: {data}")
    print("\nSuccess. Scopes granted:", data.get("scope"))
    print("Refresh token expires in about", int(data.get("refresh_expires_in", 0)) // 86400, "days.")
    print("\nSave this as the GitHub secret TIKTOK_REFRESH_TOKEN (shown once):\n")
    print(data["refresh_token"])


if __name__ == "__main__":
    main()
