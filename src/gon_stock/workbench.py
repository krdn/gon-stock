import argparse
import json
import sqlite3
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gon_stock.data_cli import private_path
from gon_stock.decisions import DecisionStore, discuss, validate_packet
from gon_stock.event_store import canonical, digest
from gon_stock.llm import ProxyClient, ProxyFailure
from gon_stock.llm_cli import load_settings


def execute(store, packet, settings):
    packet = validate_packet(packet, datetime.now(UTC))
    base, key = load_settings(settings)
    with ProxyClient(base, key) as client:
        return discuss(store, client, packet)


def make_server(db_path, settings, *, port=8765):
    with DecisionStore(db_path):
        pass
    discussion_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else canonical(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header(
                'Content-Security-Policy',
                "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.trusted_host():
                self.send(403, {'error': 'host_denied'})
                return
            assets = {
                '/': ('index.html', 'text/html'),
                '/app.js': ('app.js', 'text/javascript'),
                '/style.css': ('style.css', 'text/css'),
            }
            try:
                if self.path in assets:
                    name, content_type = assets[self.path]
                    self.send(
                        200,
                        (Path(__file__).parent / 'ui' / name).read_bytes(),
                        content_type + '; charset=utf-8',
                    )
                elif self.path == '/api/state':
                    with DecisionStore(db_path) as store:
                        self.send(
                            200,
                            {
                                'watchlist': store.watchlist(),
                                'paused': store.paused(),
                                'runs': [
                                    {
                                        'request_id': row['request_id'],
                                        'status': row['status'],
                                        'card': row['card'],
                                        'error_code': row['error_code'],
                                    }
                                    for row in store.runs()
                                ],
                                'mode': 'research',
                                'order_allowed': False,
                                'p3_status': 'pending',
                                'holdings_status': 'not_connected',
                                'buzz_status': 'not_verified',
                                'server_time': datetime.now(UTC).isoformat(),
                            },
                        )
                else:
                    self.send(404, {'error': 'not_found'})
            except (OSError, ValueError, sqlite3.Error):
                self.send(500, {'error': 'state_unavailable'})

        def do_POST(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if not self.trusted_host() or self.headers.get('Origin') != origin:
                self.send(403, {'error': 'origin_denied'})
                return
            if self.headers.get('Content-Type') != 'application/json':
                self.send(415, {'error': 'json_required'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 65536 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('invalid_body_size')
                value = json.loads(self.rfile.read(length))
                with DecisionStore(db_path) as store:
                    if self.path in ('/api/watch', '/api/unwatch'):
                        getattr(store, 'watch' if self.path.endswith('/watch') else 'unwatch')(
                            value
                        )
                    elif self.path == '/api/pause':
                        if not isinstance(value, dict) or set(value) != {'paused'}:
                            raise ValueError('invalid_pause')
                        store.pause(value['paused'])
                    elif self.path == '/api/discuss':
                        if not discussion_lock.acquire(blocking=False):
                            self.send(409, {'error': 'discussion_busy'})
                            return
                        try:
                            card = execute(store, value, settings)
                        finally:
                            discussion_lock.release()
                        self.send(200, {'request_id': card['request_id'], 'status': 'completed'})
                        return
                    else:
                        self.send(404, {'error': 'not_found'})
                        return
                self.send(200, {'status': 'ok'})
            except ProxyFailure as error:
                self.send(502, {'error': error.code})
            except (ValueError, TypeError, KeyError, OverflowError, OSError, sqlite3.Error):
                self.send(400, {'error': 'invalid_or_unavailable_request'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='연구 전용 결정 카드와 로컬 작업대')
    parser.add_argument('--db', default='.private/p4/workbench.sqlite')
    parser.add_argument('--settings', default='.private/operator-settings.json')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('discuss')
    run.add_argument('--request', required=True)
    export = commands.add_parser('export')
    export.add_argument('--request-id', required=True)
    export.add_argument('--output', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        db, settings = private_path(args.db), private_path(args.settings)
        if args.command == 'serve':
            if not 1024 <= args.port <= 65535:
                raise ValueError('invalid_port')
            server = make_server(db, settings, port=args.port)
            print(
                json.dumps(
                    {
                        'status': 'serving',
                        'url': f'http://127.0.0.1:{server.server_port}',
                        'mode': 'research',
                        'order_allowed': False,
                    }
                ),
                flush=True,
            )
            try:
                server.serve_forever()
            finally:
                server.server_close()
        else:
            with DecisionStore(db) as store:
                if args.command == 'discuss':
                    packet = json.loads(private_path(args.request).read_text())
                    card = execute(store, packet, settings)
                    print(
                        json.dumps(
                            {
                                'request_id': card['request_id'],
                                'status': 'completed',
                                'p3_status': 'pending',
                                'order_allowed': False,
                            }
                        )
                    )
                else:
                    output = private_path(args.output)
                    record = store.get(args.request_id)
                    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with output.open('x') as stream:
                        output.chmod(0o600)
                        stream.write(canonical(record))
                    print(json.dumps({'status': 'exported', 'sha256': digest(output.read_bytes())}))
    except (ValueError, TypeError, KeyError, OverflowError, OSError, sqlite3.Error, ProxyFailure):
        print(json.dumps({'status': 'failed', 'code': 'workbench_operation_failed'}))
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
