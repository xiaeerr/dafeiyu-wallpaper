"""Configuration and per-user state for the standalone release."""
import os
from pathlib import Path

STATE = Path(os.environ.get('DAFEIYU_STATE_DIR') or Path.home() / '.dafeiyu-wallpaper-release').resolve()
PROFILES = STATE / 'profiles'
PORT = int(os.environ.get('DAFEIYU_PORT', '18766'))
if not 1024 <= PORT <= 65535:
    raise ValueError('DAFEIYU_PORT must be between 1024 and 65535')
ORIGIN = f'http://127.0.0.1:{PORT}'
ASTRBOT_CORE = Path(os.environ.get('DAFEIYU_ASTRBOT_CORE') or STATE / 'astrbot').resolve()
TOKEN_FILE = STATE / 'bridge-token.txt'


def edge_executable():
    for name in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        if base := os.environ.get(name):
            candidate = Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'
            if candidate.is_file():
                return candidate
    raise FileNotFoundError('Microsoft Edge was not found.')
