import os
import socket
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, Response
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
WEB_PORT = int(os.getenv("WEB_PORT", "8099"))
SERVICE_TYPE = "_esphomelib._tcp.local."

app = Flask(__name__)

STATE = {
    "devices": [],
    "last_scan": None,
    "last_error": None,
}

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ESPHome Discovery</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #111; color: #eee; }
    h1 { margin-bottom: 8px; }
    .muted { color: #bbb; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; background: #1b1b1b; }
    th, td { padding: 10px; border: 1px solid #333; text-align: left; }
    th { background: #222; }
    tr:nth-child(even) { background: #161616; }
    code { background: #222; padding: 2px 5px; border-radius: 4px; }
    .topbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
    a { color: #66b3ff; text-decoration: none; }
  </style>
  <script>
    async function refreshData() {
      const res = await fetch('/api/devices');
      const data = await res.json();

      document.getElementById('last-scan').textContent = data.last_scan || 'never';
      document.getElementById('last-error').textContent = data.last_error || 'none';
      document.getElementById('count').textContent = data.devices.length;

      const tbody = document.getElementById('tbody');
      tbody.innerHTML = '';

      for (const d of data.devices) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${d.name || ''}</td>
          <td><code>${d.ip || ''}</code></td>
          <td>${d.port || ''}</td>
          <td><code>${d.hostname || ''}</code></td>
          <td>${d.mac || ''}</td>
          <td>${d.board || ''}</td>
          <td>${d.version || ''}</td>
        `;
        tbody.appendChild(tr);
      }
    }

    setInterval(refreshData, 5000);
    window.onload = refreshData;
  </script>
</head>
<body>
  <h1>ESPHome Devices</h1>
  <div class="topbar">
    <div>Detected devices: <strong id="count">0</strong></div>
    <div>Last scan: <span id="last-scan">never</span></div>
    <div>Last error: <span id="last-error">none</span></div>
    <div><a href="http://localhost:6052" target="_blank">ESPHome Dashboard</a></div>
  </div>

  <div class="muted">
    Live mDNS browse of ESPHome devices on your LAN.
  </div>

  <table>
    <thead>
      <tr>
        <th>Name</th>
        <th>IP</th>
        <th>Port</th>
        <th>Hostname</th>
        <th>MAC</th>
        <th>Board</th>
        <th>Version</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</body>
</html>
"""

def decode_props(properties):
    out = {}
    for k, v in (properties or {}).items():
        key = k.decode(errors="ignore") if isinstance(k, bytes) else str(k)
        if isinstance(v, bytes):
            out[key] = v.decode(errors="ignore")
        else:
            out[key] = str(v)
    return out

def parse_ip(info):
    ips = []
    for addr in info.addresses:
        try:
            if len(addr) == 4:
                ips.append(socket.inet_ntop(socket.AF_INET, addr))
            elif len(addr) == 16:
                ips.append(socket.inet_ntop(socket.AF_INET6, addr))
        except Exception:
            pass
    ipv4 = [x for x in ips if ":" not in x]
    return ipv4[0] if ipv4 else (ips[0] if ips else "")

class ESPHomeListener(ServiceListener):
    def __init__(self):
        self.devices = {}

    def update_service(self, zc, service_type, name):
        self._store(zc, service_type, name)

    def add_service(self, zc, service_type, name):
        self._store(zc, service_type, name)

    def remove_service(self, zc, service_type, name):
        self.devices.pop(name, None)

    def _store(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name, timeout=2000)
        if not info:
            return

        props = decode_props(info.properties)
        ip = parse_ip(info)

        self.devices[name] = {
            "name": props.get("name") or name.replace(f".{SERVICE_TYPE}", "").strip("."),
            "ip": ip,
            "port": info.port,
            "hostname": info.server.rstrip(".") if info.server else "",
            "mac": props.get("mac", ""),
            "board": props.get("board", ""),
            "version": props.get("version", ""),
        }

def scanner_loop():
    while True:
        zc = None
        try:
            listener = ESPHomeListener()
            zc = Zeroconf()
            browser = ServiceBrowser(zc, SERVICE_TYPE, listener)
            time.sleep(6)

            devices = sorted(listener.devices.values(), key=lambda d: (d["name"], d["ip"]))
            STATE["devices"] = devices
            STATE["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            STATE["last_error"] = None
        except Exception as e:
            STATE["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            STATE["last_error"] = str(e)
        finally:
            if zc is not None:
                try:
                    zc.close()
                except Exception:
                    pass

        time.sleep(SCAN_INTERVAL)

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/api/devices")
def api_devices():
    return jsonify(STATE)

if __name__ == "__main__":
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=WEB_PORT)
