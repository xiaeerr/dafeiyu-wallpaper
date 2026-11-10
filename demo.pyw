"""Open an independent fullscreen demonstration window."""
import ctypes
from pathlib import Path
from data_paths import PORT, ORIGIN, PROFILES, edge_executable
import socket
import subprocess
import sys
import time


def bridge_ready():
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', PORT)) == 0


def main():
    root = Path(__file__).resolve().parent
    edge = edge_executable()
    profile = PROFILES / 'demo-profile'
    if not bridge_ready():
        subprocess.Popen(
            [sys.executable, str(root / 'bridge.py')],
            cwd=root,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 12
        while not bridge_ready():
            if time.monotonic() >= deadline:
                raise RuntimeError('本地壁纸服务未能启动。')
            time.sleep(0.2)
    subprocess.Popen([
        str(edge), '--kiosk', ORIGIN+'/app/index.html?demo=1',
        '--edge-kiosk-type=fullscreen', '--user-data-dir=' + str(profile),
        '--no-first-run', '--disable-background-mode', '--kiosk-idle-timeout-minutes=0',
    ])


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), '大肥鱼桌面演示版', 0x10)
