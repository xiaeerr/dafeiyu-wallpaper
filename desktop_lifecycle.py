"""Lifecycle helpers: stop conflicting renderer, recover once per resume gap."""
import subprocess,time,json,os
from pathlib import Path
from data_paths import STATE
ROOT=Path(__file__).parent;DATA=STATE
def stop_competitor():
 path=os.environ.get('DAFEIYU_WALLPAPER_ENGINE_EXE')
 if not path:return False
 exe=Path(path)
 if not exe.is_absolute() or exe.name.lower() not in ('wallpaper32.exe','wallpaper64.exe') or not exe.is_file():
  return False
 try:
  renderers=subprocess.run(['tasklist','/FI','IMAGENAME eq webwallpaper64.exe','/FO','CSV','/NH'],
                           capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=5,check=True)
  if b'"webwallpaper64.exe"' not in renderers.stdout.lower():return False
  subprocess.run([str(exe),'-control','stop'],creationflags=subprocess.CREATE_NO_WINDOW,timeout=8,check=True)
  return True
 except (OSError,subprocess.SubprocessError):
  return False

def enabled():
 try:return json.loads((DATA/'desktop-session.json').read_text(encoding='utf-8')).get('enabled',False)
 except Exception:return False
class ResumeDetector:
 def __init__(self,now):self.last=now;self.pending=0
 def step(self,now):
  if now-self.last>30:self.pending=now+10
  self.last=now
  if self.pending and now>=self.pending:
   self.pending=0;return True
  return False

def guard():
 import sys
 detector=ResumeDetector(time.monotonic());last_check=0
 while True:
  time.sleep(5);now=time.monotonic()
  recovered=detector.step(now)
  if not enabled():continue
  try:
   if now-last_check>15:
    last_check=now
    stop_competitor()
   if recovered:
    # One request for this resume only. No browser restart loop.
    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'launch.pyw')],cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
  except Exception:pass
