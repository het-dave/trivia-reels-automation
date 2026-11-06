"""Instagram API with Unified login / Facebook Login for Business (graph.facebook.com, API v27.0).

Upload path: Meta's direct resumable upload (rupload.facebook.com) rejects this account's videos longer than
~45-60 s with ProcessingFailedError (probed 2026-11-06: 30 s and 45 s OK, 60 s+ fail), while video_url
containers accept full-length reels. So each reel is served from a throwaway public `media` branch
(raw.githubusercontent.com: direct, no redirect, no expiring signature) and the branch is deleted right after.

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

    def _call(self, method: str, url: str, params: dict | None = None, timeout: int = 120) -> dict:
        data = None
        if params and method == "GET":
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"OAuth {self._token}"})
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

    def create_container(self, caption: str, video_url: str) -> str:
        return self._call("POST", f"{self.graph}/{self.user_id}/media", {
            "media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true", "thumb_offset": "1000",
        })["id"]

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

    def prepare(self, mp4: Path, caption: str, timeout_s: int, poll_s: int, log=print) -> str:
        """Host the file, let Meta fetch + process it, then remove it. Returns a FINISHED container id."""
        from . import state

        url = state.host_on_media_branch(mp4)
        try:
            cid = self.create_container(caption, url)
            log(f"  container {cid} created from {mp4.stat().st_size / 1e6:.1f} MB file, waiting for Meta to process it")
            self.wait_finished(cid, timeout_s, poll_s)
        finally:
            state.drop_media_branch()
        return cid

    def publish_reel(self, mp4: Path, caption: str, cfg: dict, log=print) -> dict:
        ic = cfg["instagram"]
        cid = self.prepare(mp4, caption, ic["status_timeout_seconds"], ic["status_poll_seconds"], log)
        media_id = self._call("POST", f"{self.graph}/{self.user_id}/media_publish", {"creation_id": cid})["id"]
        try:
            permalink = self._call("GET", f"{self.graph}/{media_id}", {"fields": "permalink"}).get("permalink", "")
        except GraphError:
            permalink = ""
        return {"media_id": media_id, "container_id": cid, "permalink": permalink}


def diagnose(version: str = "v27.0") -> int:
    """`python -m trivia.instagram [--upload-probe]`: check the stored token + account ID (and the upload path).
    Prints API results, never the token."""
    import os
    import sys

    token, uid = os.environ.get("IG_ACCESS_TOKEN", ""), os.environ.get("IG_USER_ID", "").strip()
    print(f"IG_ACCESS_TOKEN set: {bool(token)} | IG_USER_ID set: {bool(uid)}, {len(uid)} chars, "
          f"digits only: {uid.isdigit()}, starts with 17841 (professional-account ID format): {uid.startswith('17841')}")
    if not token:
        return 1
    ig = IG(token, uid or "-", version)
    checks = [
        ("granted permissions", "me/permissions", {}),
        ("Instagram accounts assigned to this token (Unified login)", "me/assigned_instagram_accounts", {"fields": "id,username"}),
        ("IG_USER_ID -> account", uid or "-", {"fields": "username"}),
        ("publishing quota", f"{uid or '-'}/content_publishing_limit", {"fields": "quota_usage,config"}),
    ]
    ok = True
    for label, path, params in checks:
        try:
            print(f"OK   {label}: {json.dumps(ig._call('GET', f'{ig.graph}/{path}', params))[:800]}")
        except (AuthError, GraphError) as e:
            ok = ok and label.startswith("Instagram accounts assigned")  # optional lookup
            print(f"FAIL {label}: {e}")
    if ok and "--upload-probe" in sys.argv:
        ok = upload_probe(ig)
    return 0 if ok else 1


def upload_probe(ig: IG) -> bool:
    """Run the real upload path on a 60 s test clip, up to FINISHED. It is never published (Meta drops it after 24 h)."""
    import tempfile

    from .render import instagram_remux

    d = Path(tempfile.mkdtemp())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=60", "-f", "lavfi", "-i", "sine=f=440:d=60",
                    "-c:v", "libx264", "-preset", "veryfast", "-b:v", "300k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest",
                    str(d / "raw.mp4")], check=True)
    instagram_remux(d / "raw.mp4", d / "probe.mp4")
    try:
        ig.prepare(d / "probe.mp4", "upload probe (never published)", 240, 10)
        print("OK   upload probe: 60 s clip fetched by Meta and FINISHED processing (not published); media branch removed")
        return True
    except (AuthError, GraphError, subprocess.CalledProcessError) as e:
        print(f"FAIL upload probe: {e}")
        return False


if __name__ == "__main__":
    import sys

    sys.exit(diagnose())
