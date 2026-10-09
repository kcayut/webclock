"""Run separate Home Assistant Ingress and LAN display listeners."""
import os
from socket import gethostname
from threading import Thread

from werkzeug.serving import make_server

from webclock.app import app


def main():
    host = os.getenv('HOST', '0.0.0.0')
    display = make_server(host, int(os.getenv('WEBCLOCK_DISPLAY_PORT', '8100')), app, threaded=True)
    try:
        ingress = make_server(host, int(os.getenv('WEBCLOCK_INGRESS_PORT', '8099')), app, threaded=True)
    except Exception:
        display.server_close()
        raise
    worker = Thread(target=ingress.serve_forever, daemon=True)
    worker.start()
    print(f'Home Assistant integration URL: http://{gethostname()}:{display.server_port}', flush=True)
    try:
        display.serve_forever()
    finally:
        ingress.shutdown()
        ingress.server_close()
        display.server_close()


if __name__ == '__main__':
    main()
