"""Send local speech requests to one reusable WSL worker."""

from collections import deque
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import tempfile
import threading
import time
import wave


class LocalVoiceError(ValueError):
    pass


_inference = threading.Lock()
_profile = 'runtime.tts.cuda.local.json'
_worker = None


def read_config(data):
    try:
        with (data / 'feiyu-voice-root.txt').open(encoding='utf-8') as file:
            version = os.fstat(file.fileno()).st_mtime_ns
            root = Path(file.read().strip())
    except FileNotFoundError:
        return None, 0
    return root, version


def _wsl_path(path):
    path = path.resolve()
    if not re.fullmatch(r'[a-zA-Z]:', path.drive):
        raise LocalVoiceError('本机大肥鱼声线需要安装在本地磁盘')
    return f'/mnt/{path.drive[0].lower()}/' + '/'.join(path.parts[1:])


class Worker:
    def __init__(self, root, profile, package):
        runtime = json.loads(profile.read_text(encoding='utf-8'))
        model_dir = runtime.get('wallpaper_model_dir') or _wsl_path(package)
        command = ['wsl.exe', '-d', runtime['distribution'], '--', 'env']
        if library := runtime.get('python_library_dir'):
            command.append('LD_LIBRARY_PATH=' + library)
        command += [runtime['python'], '-Bu', _wsl_path(Path(__file__).with_name('feiyu_wsl_worker.py')),
                    _wsl_path(root / 'wetext'), _wsl_path(profile.parent.parent), model_dir, _wsl_path(profile)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        self.key = (root, profile.stat().st_mtime_ns)
        self.used_at = time.monotonic()
        self.replies = Queue()
        self.logs = deque(maxlen=80)
        threading.Thread(target=self.read_replies, daemon=True).start()
        threading.Thread(target=self.read_logs, daemon=True).start()

    def read_replies(self):
        with self.process.stdout as stream:
            for line in stream:
                if line.strip() == b'{"ok":true}':
                    self.replies.put(True)
        self.replies.put(False)

    def read_logs(self):
        with self.process.stderr as stream:
            for line in stream:
                self.logs.append(line)

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass

    def request(self, text, path):
        payload = json.dumps({'text': text, 'output': _wsl_path(path)}, ensure_ascii=False)
        self.process.stdin.write(payload.encode('utf-8') + b'\n')
        self.process.stdin.flush()
        if not self.replies.get(timeout=120):
            raise LocalVoiceError('本机大肥鱼语音生成失败，请检查 Ubuntu 和显卡是否可用')
        self.used_at = time.monotonic()


def _close_worker():
    global _worker
    if _worker is not None:
        _worker.close()
        _worker = None


def release_idle():
    if _inference.acquire(blocking=False):
        try:
            _close_worker()
        finally:
            _inference.release()


def synthesize(text, root, *, diagnostic=None):
    global _worker
    server = root / 'source' / 'server'
    profile = server / 'configs' / _profile
    package = server / 'models' / 'FeiyuVoice-CosyVoice3'
    if not profile.is_file() or not (package / 'files_sha256.json').is_file():
        raise LocalVoiceError('本机大肥鱼声线尚未安装完成')
    if not _inference.acquire(blocking=False):
        raise LocalVoiceError('本机大肥鱼正在生成另一条语音，请稍后再试')
    worker = None
    try:
        key = (root, profile.stat().st_mtime_ns)
        if (_worker is None or _worker.key != key or _worker.process.poll() is not None
                or time.monotonic() - _worker.used_at > 40):
            _close_worker()
            _worker = Worker(root, profile, package)
        worker = _worker
        with tempfile.TemporaryDirectory(prefix='speech-', dir=root) as work:
            path = Path(work) / 'speech.wav'
            worker.request(text, path)
            with wave.open(str(path), 'rb') as clip:
                if clip.getframerate() != 24000 or not 2400 < clip.getnframes() <= 24000 * 360:
                    raise LocalVoiceError('本机大肥鱼返回了无效的语音')
            return path.read_bytes()
    except Empty:
        _close_worker()
        raise LocalVoiceError('本机大肥鱼语音生成超时，请试试短一点的内容') from None
    except LocalVoiceError:
        _close_worker()
        raise
    except (OSError, KeyError, json.JSONDecodeError, EOFError, wave.Error):
        _close_worker()
        raise LocalVoiceError('本机大肥鱼语音暂时不可用') from None
    finally:
        _inference.release()
        if diagnostic is not None and worker is not None:
            diagnostic.write_bytes(b''.join(worker.logs.copy()))
