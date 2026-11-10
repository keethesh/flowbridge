"""Google Flow (flow.google.com) as an API, backed by your logged-in browser via `browse`.

Flow's generate RPCs need a fresh reCAPTCHA Enterprise token per call, so requests are
executed inside a real Flow tab (see flow_page.js); this module only drives that tab.

    from flowbridge import Flow
    f = Flow()                      # project: arg, $FLOW_PROJECT, else a reused "Flow API" project
    f.image("a red apple")          # -> [{"media_id", "url"}]   (images cost 0 credits)
    f.video("a paper boat", out="boat.mp4")

    python -m flowbridge serve --port 8787   # HTTP API for other languages
"""
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE_JS = (Path(__file__).with_name("flow_page.js")).read_text()

# Relay-side wrapper: make sure the session tab is a logged-in Flow page, then run PAGE_JS in it.
DRIVER_JS = r"""
const A = __ARGS__;
const want = 'https://flow.google.com/' + (A.project ? 'project/' + A.project : '');
if (!page.url().startsWith('https://flow.google.com/')) await page.goto(want);
for (let i = 0; ; i++) {
  if (await page.evaluate('!!window.WIZ_global_data?.SNlM0e', undefined, undefined, false)) break;
  if (page.url().includes('accounts.google.com') || i > 60)
    throw new Error('Flow not ready (logged out?). Log in at flow.google.com in the browse-connected Chrome. url=' + page.url());
  await page.waitForTimeout(500);
}
const run = (args) => page.evaluate('(' + __PAGE_JS__ + ')(' + JSON.stringify(args) + ')', undefined, undefined, false);
const res = await run(A);
if (A.op !== 'media' || !A.resolve || res.status !== 'success' || !res.asb_url) return res;
// The asb URL 302s to an IP-bound signed googlevideo URL that the page cannot read (CORS);
// load it in a hidden <video> and capture the redirect target from the network instead.
const got = new Promise((ok) => {
  const h = (r) => { if (r.url().includes('googlevideo.com/videoplayback')) { page.off('request', h); ok(r.url()); } };
  page.on('request', h);
  setTimeout(() => { page.off('request', h); ok(null); }, 20000);
});
await page.evaluate((u) => { const v = document.createElement('video'); v.muted = true; v.preload = 'auto'; v.src = u; v.hidden = true; document.body.appendChild(v); setTimeout(() => v.remove(), 25000); }, res.asb_url, undefined, false);
res.url = await got;
return res;
"""


class FlowError(RuntimeError):
    pass


class Flow:
    def __init__(self, project=None, session="flowbridge", browse="browse"):
        self.session = session
        self.browse = shutil.which(browse)
        if not self.browse:
            raise FlowError("`browse` CLI not found; install it: curl -fsSL https://opencode.ai/browse/install | bash")
        self._lock = threading.Lock()  # one browser tab: serialize calls
        r = subprocess.run([self.browse, "session", "new", session], capture_output=True, text=True)
        if r.returncode and "already exists" not in r.stderr + r.stdout:
            raise FlowError(f"browse session new failed: {r.stderr or r.stdout}")
        self.project = project or os.environ.get("FLOW_PROJECT") or self._default_project()

    def _default_project(self, title="Flow API"):
        # shortcut: only the ~21 most recent projects are searched; older "Flow API" projects get a new sibling
        return next((p["id"] for p in self.projects() if p["title"] == title), None) or self.create_project(title)

    def _call(self, op, timeout=120, **args):
        args = {"op": op, "project": getattr(self, "project", None), **{k: v for k, v in args.items() if v is not None}}
        code = DRIVER_JS.replace("__ARGS__", json.dumps(args)).replace("__PAGE_JS__", json.dumps(PAGE_JS))
        with self._lock, tempfile.NamedTemporaryFile("w", suffix=".js") as f:
            f.write(code)
            f.flush()
            r = subprocess.run(
                [self.browse, "execute", "--session", self.session, "--json", "--timeout-ms", str(timeout * 1000), "--file", f.name],
                capture_output=True, text=True, timeout=timeout + 30,
            )
        try:
            env = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise FlowError(f"{op}: {r.stderr or r.stdout}") from None
        if not env.get("ok") or env.get("isError"):
            raise FlowError(f"{op}: {env.get('error') or env.get('text')}")
        return env["value"]

    def credits(self):
        return self._call("credits")

    def models(self):
        return self._call("models")

    def projects(self):
        """Most recent projects: [{id, title}]."""
        return self._call("projects")

    def create_project(self, title="Flow API"):
        return self._call("create_project", title=title)

    def image(self, prompt, model="BELUGA", aspect="16:9", count=1, seed=None, out_dir=None):
        """Nano Banana image(s). Returns [{media_id, url}]; url is a signed, cookie-free link (~6h)."""
        res = self._call("image", prompt=prompt, model=model, aspect=aspect, count=count, seed=seed)
        if out_dir:
            for m in res:
                m["path"] = _download(m["url"], Path(out_dir) / f"{m['media_id']}.jpg")
        return res

    def upload(self, path):
        """Upload a local image into the project; returns its media_id (usable as a video frame)."""
        p = Path(path)
        return self._call("upload", data=base64.b64encode(p.read_bytes()).decode(),
                          mime=mimetypes.guess_type(p.name)[0] or "image/jpeg", filename=p.name)

    def _frame(self, x):
        # local file -> upload it; anything else is taken as an existing Flow image media_id
        return self.upload(x) if x and Path(x).is_file() else x

    def submit_video(self, prompt, model=None, aspect="16:9", start_image=None, end_image=None):
        """Spends credits. Returns {media_id, credits_left}.

        start_image / end_image: local image path or Flow image media_id. start only = image-to-video,
        start + end = first/last frame. model defaults per mode to Omni 1.2 Flash 8s 360p
        (macaron_cookie_{t2v,i2v,i2v_fl}_8s_360p, 8 credits); other keys: models().
        """
        return self._call("video", prompt=prompt, model=model, aspect=aspect,
                          start_image=self._frame(start_image), end_image=self._frame(end_image))

    def media(self, media_id, resolve=True):
        """{media_id, status: pending|success|failed|canceled, asb_url, url}; url is the IP-bound mp4 link."""
        return self._call("media", media_id=media_id, resolve=resolve)

    def video(self, prompt, model=None, aspect="16:9", start_image=None, end_image=None, out=None, timeout=600, poll=8):
        job = self.submit_video(prompt, model=model, aspect=aspect, start_image=start_image, end_image=end_image)
        deadline = time.time() + timeout
        while True:
            m = self.media(job["media_id"], resolve=False)
            if m["status"] != "pending":
                break
            if time.time() > deadline:
                raise FlowError(f"video {job['media_id']} still pending after {timeout}s")
            time.sleep(poll)
        if m["status"] != "success":
            raise FlowError(f"video {job['media_id']} {m['status']}")
        m = self.media(job["media_id"])
        m["credits_left"] = job["credits_left"]
        if out:
            if not m.get("url"):
                raise FlowError(f"could not resolve download URL for {job['media_id']}")
            m["path"] = _download(m["url"], Path(out))
        return m


def _download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # googlevideo 403s non-browser user agents
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"})
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return str(path)


def serve(port=8787, host="127.0.0.1"):
    flow = Flow()
    print(f"Flow API on http://{host}:{port}  project={flow.project}")

    routes = {
        ("GET", "/credits"): lambda b: flow.credits(),
        ("GET", "/models"): lambda b: flow.models(),
        ("GET", "/projects"): lambda b: flow.projects(),
        ("POST", "/projects"): lambda b: flow.create_project(b.get("title", "Flow API")),
        ("POST", "/images"): lambda b: flow.image(**b),
        ("POST", "/uploads"): lambda b: flow.upload(b["path"]),
        ("POST", "/videos"): lambda b: flow.video(**b) if b.pop("wait", False) else flow.submit_video(**b),
    }

    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("content-length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if method == "GET" and self.path.startswith("/media/"):
                    out = flow.media(self.path.split("/")[2])
                elif (method, self.path) in routes:
                    out = routes[(method, self.path)](body)
                else:
                    return self._send(404, {"error": "not found"})
                self._send(200, out)
            except (FlowError, TypeError, ValueError, KeyError, OSError) as e:
                self._send(400, {"error": str(e)})

        def _send(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = lambda self: self._go("GET")
        do_POST = lambda self: self._go("POST")

    ThreadingHTTPServer((host, port), H).serve_forever()
