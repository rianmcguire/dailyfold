import http.server
import socketserver
from pathlib import Path

SNAP_DIR = Path(__file__).parent / "snapshots"
SNAP_DIR.mkdir(exist_ok=True)
PORT = 8765
LATEST = SNAP_DIR / "latest.png"

INDEX_HTML = """<!doctype html>
<html><head><title>dailyfold</title>
<style>
body{margin:0;background:#1c1d20;display:flex;align-items:center;justify-content:center;min-height:100vh;color:#888;font-family:sans-serif}
img{max-width:95vw;max-height:95vh;border:1px solid #333;background:#000}
.empty{opacity:.6}
</style></head>
<body><img id=i src="/latest.png" onerror="this.style.display='none';document.getElementById('e').style.display='block'">
<div id=e class=empty style="display:none">no snapshot yet — run <code>python3 app.py --snapshot</code></div>
<script>
let last = '';
async function poll() {
  try {
    const h = await fetch('/latest.png', {method:'HEAD', cache:'no-store'});
    const m = h.headers.get('last-modified') || '';
    if (m && m !== last) {
      last = m;
      const img = document.getElementById('i');
      img.src = '/latest.png?t=' + Date.now();
      img.style.display = '';
      document.getElementById('e').style.display = 'none';
    }
  } catch {}
}
setInterval(poll, 500); poll();
</script></body></html>
""".encode("utf-8")


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", INDEX_HTML)
            return
        super().do_GET()

    def do_HEAD(self):
        super().do_HEAD()

    def translate_path(self, path):
        path = path.split("?", 1)[0]
        if path == "/latest.png":
            return str(LATEST)
        return super().translate_path(path)

    def log_message(self, *a, **kw):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with Server(("0.0.0.0", PORT), Handler) as srv:
        print(f"serving on http://0.0.0.0:{PORT}", flush=True)
        srv.serve_forever()
