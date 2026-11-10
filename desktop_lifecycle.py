"""Lifecycle helpers: stop conflicting renderer, recover once per resume gap."""
import subprocess,time,json
from pathlib import Path
from data_paths import STATE
ROOT=Path(__file__).parent;DATA=STATE
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
 detector=ResumeDetector(time.monotonic())
 while True:
  time.sleep(5);now=time.monotonic()
  recovered=detector.step(now)
  if not enabled():continue
  try:
   if recovered:
    # One request for this resume only. No browser restart loop.
    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'launch.pyw')],cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
  except Exception:pass
