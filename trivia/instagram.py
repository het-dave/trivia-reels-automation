"""Instagram API with Facebook Login (graph.facebook.com) - resumable Reels upload, no public video URL needed.

Docs: developers.facebook.com/docs/instagram-platform/content-publishing (checked 2026-11, API v27.0).
The token only ever travels in the Authorization header, never in URLs or logs.
"""
import json
import subprocess
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
            raw = e.read()
            try:
                err = json.loads(raw).get("error", {})
            except ValueError:
                err = {}
            detail = err.get("message") or raw.decode("utf-8", "replace")[:600] or e.reason
            msg = f"Graph API HTTP {e.code}: {detail} (code {err.get('code')}, subcode {err.get('error_subcode')})"
            if e.code == 401 or err.get("code") in AUTH_CODES:
                raise AuthError(msg) from None
            raise GraphError(msg) from None

    def recent_media(self, limit: int = 25) -> list[dict]:
        r = self._call("GET", f"{self.graph}/{self.user_id}/media", {"fields": "id,caption,timestamp,media_product_type", "limit": limit})
        return r.get("data", [])

    def username(self) -> str:
        return self._call("GET", f"{self.graph}/{self.user_id}", {"fields": "username"}).get("username", "")

    def create_container(self, caption: str, video_url: str | None = None) -> tuple[str, str]:
        """Resumable container (we upload the bytes), or with video_url Meta fetches the file itself."""
        params = {"media_type": "REELS", "caption": caption, "share_to_feed": "true", "thumb_offset": "1000"}
        params.update({"video_url": video_url} if video_url else {"upload_type": "resumable"})
        c = self._call("POST", f"{self.graph}/{self.user_id}/media", params)
        return c["id"], c.get("uri") or f"{self.rupload}/{c['id']}"

    def upload(self, uri: str, mp4: Path) -> None:
        """Resumable upload exactly as Meta's example: curl with lowercase `offset` / `file_size` headers.
        Headers go through stdin (-H @-), so the token never appears in a process list."""
        hdr = f"Authorization: OAuth {self._token}\noffset: 0\nfile_size: {mp4.stat().st_size}\n"
        r = subprocess.run(["curl", "-sS", "--max-time", "900", "-X", "POST", uri, "-H", "@-", "--data-binary", f"@{mp4}", "-w", "\n%{http_code}"],
                           input=hdr, capture_output=True, text=True)
        if r.returncode != 0:
            raise GraphError(f"upload failed: curl exit {r.returncode}: {r.stderr.strip()[-300:]}")
        body, _, code = r.stdout.rpartition("\n")
        if code != "200" or '"success":true' not in body.replace(" ", ""):
            msg = f"upload HTTP {code}: {body[:600]}"
            raise (AuthError if code == "401" or "OAuthException" in body else GraphError)(msg)

    def wait_finished(self, cid: str, timeout_s: int, poll_s: int) -> None:
        deadline = time.time() + timeout_s
        while True:
            st = self._call("GET", f"{self.graph}/{cid}", {"fields": "status_code,status"})
            code = st.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise GraphError(f"container {cid} {code}: {st.get('status')}")
            if time.time() > deadline:
                raise GraphError(f"container {cid} still {code} after {timeout_s}s")
            time.sleep(poll_s)

    def publish_reel(self, mp4: Path, caption: str, cfg: dict, log=print) -> dict:
        ic = cfg["instagram"]
        cid, uri = self.create_container(caption)
        log(f"  container {cid} created, uploading {mp4.stat().st_size / 1e6:.1f} MB")
        self.upload(uri, mp4)
        self.wait_finished(cid, ic["status_timeout_seconds"], ic["status_poll_seconds"])
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
        ("granted permissions", "me/permissions", {}),
        ("Instagram accounts assigned to this token (Unified login)", "me/assigned_instagram_accounts", {"fields": "id,username"}),
        ("Pages + linked Instagram accounts", "me/accounts", {"fields": "name,instagram_business_account{id,username}"}),
        ("IG_USER_ID -> account", uid or "-", {"fields": "username"}),
        ("publishing quota", f"{uid or '-'}/content_publishing_limit", {"fields": "quota_usage,config"}),
    ]
    ok = True
    for label, path, params in checks:
        try:
            print(f"OK   {label}: {json.dumps(ig._call('GET', f'{ig.graph}/{path}', params))[:800]}")
        except (AuthError, GraphError) as e:
            ok = ok and label.startswith(("Pages", "Instagram accounts assigned"))  # optional lookups
            print(f"FAIL {label}: {e}")
    if ok and "--upload-probe" in __import__("sys").argv:
        ok = upload_probe(ig)
    return 0 if ok else 1


def upload_probe(ig: IG) -> bool:
    """Upload test clips to containers that are never published (Meta drops them after 24 h).
    Variants isolate what Meta's upload host accepts: plain encode, our Instagram remux, remux without
    negative CTS offsets, and a reel-sized file."""
    import tempfile

    from .render import instagram_remux

    d = Path(tempfile.mkdtemp())

    def encode(name: str, seconds: int, extra: list[str]) -> Path:
        out = d / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={seconds}", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", *extra, "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest",
                        "-movflags", "+faststart", str(out)], check=True)
        return out

    from . import state

    ok = True
    for label, secs, rate, via_url in [("30s direct upload", 30, "200k", False), ("45s direct upload", 45, "200k", False),
                                       ("60s via video_url", 60, "200k", True), ("176s via video_url", 176, "200k", True)]:
        raw = encode(f"p{secs}{'u' if via_url else 'd'}", secs, ["-b:v", rate, "-maxrate", rate, "-bufsize", rate])
        mp4 = d / f"ig_{raw.name}"
        instagram_remux(raw, mp4)
        try:
            if via_url:
                url = state.host_on_media_branch(mp4)
                cid, _ = ig.create_container(f"upload probe: {label} (never published)", video_url=url)
            else:
                cid, uri = ig.create_container(f"upload probe: {label} (never published)")
                ig.upload(uri, mp4)
            ig.wait_finished(cid, 240, 10)
            print(f"OK   probe [{label}, {mp4.stat().st_size / 1e6:.1f} MB]: accepted + FINISHED (not published)")
        except (AuthError, GraphError) as e:
            ok = False
            print(f"FAIL probe [{label}, {mp4.stat().st_size / 1e6:.1f} MB]: {e}")
        finally:
            if via_url:
                state.drop_media_branch()
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(diagnose())
