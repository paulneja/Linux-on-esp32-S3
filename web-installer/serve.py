#!/usr/bin/env python3
"""Serve the installer on loopback (a trustworthy Web Serial origin)."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8080)
args = parser.parse_args()
handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parent))
print(f'Open in Google Chrome: http://127.0.0.1:{args.port}', flush=True)
try:
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        server.serve_forever()
except KeyboardInterrupt:
    pass
