"""Instagram API with Facebook Login (graph.facebook.com) - resumable Reels upload, no public video URL needed.

Docs: developers.facebook.com/docs/instagram-platform/content-publishing (checked 2026-11, API v27.0).
The token only ever travels in the Authorization header, never in URLs or logs.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_CODES = {102, 190, 10, 200, 210}  # session/token invalid, or permission missing


class AuthError(RuntimeError):
    pass


class GraphError(RuntimeError):
    pass


class IG:
    def __init__(self, token: str, user_id: str, version: str):
        if not token or not user_id:
            raise AuthError("IG_ACCESS_TOKEN / IG_USER_ID secrets are not set")
        self._token, self.user_id = token, user_id
        self.graph = f"https://graph.facebook.com/{version}"
        self.rupload = f"https://rupload.facebook.com/ig-api-upload/{version}"

    def _call(self, method: str, url: str, params: dict | None = None, data: bytes | None = None, headers: dict | None = None, timeout: int = 120) -> dict:
        if params and method == "GET":
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"OAuth {self._token}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", {})
            except ValueError:
                err = {}
            msg = f"Graph API HTTP {e.code}: {err.get('message', e.reason)} (code {err.get('code')}, subcode {err.get('error_subcode')})"
            if e.code == 401 or err.get("code") in AUTH_CODES:
                raise AuthError(msg) from None
            raise GraphError(msg) from None

    def recent_media(self, limit: int = 25) -> list[dict]:
        r = self._call("GET", f"{self.graph}/{self.user_id}/media", {"fields": "id,caption,timestamp,media_product_type", "limit": limit})
        return r.get("data", [])

    def username(self) -> str:
        return self._call("GET", f"{self.graph}/{self.user_id}", {"fields": "username"}).get("username", "")

    def publish_reel(self, mp4: Path, caption: str, cfg: dict, log=print) -> dict:
        ic = cfg["instagram"]
        c = self._call("POST", f"{self.graph}/{self.user_id}/media", {
            "media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true", "thumb_offset": "1000",
        })
        cid = c["id"]
        log(f"  container {cid} created, uploading {mp4.stat().st_size / 1e6:.1f} MB")
        body = mp4.read_bytes()
        up = self._call("POST", c.get("uri") or f"{self.rupload}/{cid}", data=body, timeout=600,
                        headers={"offset": "0", "file_size": str(len(body)), "Content-Type": "application/octet-stream"})
        if not up.get("success"):
            raise GraphError(f"upload failed: {up}")
        deadline = time.time() + ic["status_timeout_seconds"]
        while True:
            st = self._call("GET", f"{self.graph}/{cid}", {"fields": "status_code,status"})
            code = st.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise GraphError(f"container {cid} {code}: {st.get('status')}")
            if time.time() > deadline:
                raise GraphError(f"container {cid} still {code} after {ic['status_timeout_seconds']}s")
            time.sleep(ic["status_poll_seconds"])
        media_id = self._call("POST", f"{self.graph}/{self.user_id}/media_publish", {"creation_id": cid})["id"]
        try:
            permalink = self._call("GET", f"{self.graph}/{media_id}", {"fields": "permalink"}).get("permalink", "")
        except GraphError:
            permalink = ""
        return {"media_id": media_id, "container_id": cid, "permalink": permalink}


def diagnose(version: str = "v27.0") -> int:
    """`python3 -m trivia.instagram`: check the stored token + account ID. Prints API results, never the token."""
    import os

    token, uid = os.environ.get("IG_ACCESS_TOKEN", ""), os.environ.get("IG_USER_ID", "").strip()
    print(f"IG_ACCESS_TOKEN set: {bool(token)} | IG_USER_ID set: {bool(uid)}, {len(uid)} chars, "
          f"digits only: {uid.isdigit()}, starts with 17841 (professional-account ID format): {uid.startswith('17841')}")
    if not token:
        return 1
    ig = IG(token, uid or "-", version)
    checks = [
        ("token owner", "me", {"fields": "name"}),
        ("granted permissions", "me/permissions", {}),
        ("Pages + linked Instagram accounts", "me/accounts", {"fields": "name,instagram_business_account{id,username}"}),
        ("IG_USER_ID -> account", uid or "-", {"fields": "username"}),
        ("publishing quota", f"{uid or '-'}/content_publishing_limit", {"fields": "quota_usage,config"}),
    ]
    ok = True
    for label, path, params in checks:
        try:
            print(f"OK   {label}: {json.dumps(ig._call('GET', f'{ig.graph}/{path}', params))[:800]}")
        except (AuthError, GraphError) as e:
            ok = ok and label in ("Pages + linked Instagram accounts",)  # optional: needs pages_show_list
            print(f"FAIL {label}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(diagnose())
