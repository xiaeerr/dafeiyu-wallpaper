import socket,subprocess,sys,time,json,os,msvcrt,ctypes
from pathlib import Path
from data_paths import STATE, PROFILES, PORT, ORIGIN, edge_executable
root=Path(__file__).parent;data=STATE;data.mkdir(exist_ok=True)
lock=open(data/'launch.lock','a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:raise SystemExit(0)
def bridge_running():
 with socket.socket() as sock:sock.settimeout(1);return sock.connect_ex(('127.0.0.1',PORT))==0
def record(ok,message):
 (data/'desktop-session.json').write_text(json.dumps({'enabled':bool(ok)}),encoding='utf-8')
 (data/'launch-status.json').write_text(json.dumps({'ok':ok,'message':message,'at':time.time()},ensure_ascii=False),encoding='utf-8')
try:
 if '--startup' in sys.argv:
  import desktop_pin
  deadline=time.monotonic()+45
  while not (desktop_pin.u.FindWindowW('Shell_TrayWnd',None) and desktop_pin.u.FindWindowW('Progman',None)):
   if time.monotonic()>=deadline:break  # pin() also waits for Explorer's wallpaper layer.
   time.sleep(.5)
 if not bridge_running():
  subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(root/'bridge.py')],cwd=str(root),creationflags=subprocess.CREATE_NO_WINDOW)
  for _ in range(60):
   time.sleep(.2)
   if bridge_running():break
 if not bridge_running():raise RuntimeError('本地服务未能启动')
 import desktop_pin
 existing=desktop_pin.pinned_hwnd()
 mode_file=data/'display-mode.json'
 try:mode=json.loads(mode_file.read_text(encoding='utf-8')).get('mode')
 except Exception:mode=None
 if existing and mode=='kiosk-stable-v3' and '--reload' not in sys.argv:
  ok,message=desktop_pin.pin(30);record(ok,message);raise SystemExit(0 if ok else 1)
 if existing:
  # Close only this application's own window when upgrading its display mode.
  desktop_pin.u.PostMessageW.argtypes=[ctypes.wintypes.HWND,ctypes.wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t]
  desktop_pin.u.PostMessageW(existing,0x0010,0,0)
  for _ in range(60):
   time.sleep(.1)
   if not desktop_pin.pinned_hwnd():break
 edge=edge_executable()
 subprocess.Popen([str(edge),'--kiosk',ORIGIN+'/app/index.html?desktop=1','--edge-kiosk-type=fullscreen','--autoplay-policy=no-user-gesture-required','--kiosk-idle-timeout-minutes=0','--disable-background-mode','--no-first-run','--user-data-dir='+str(PROFILES/'wallpaper-profile'),'--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding','--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling'],creationflags=subprocess.CREATE_NO_WINDOW)
 time.sleep(2)
 if '--window-test' in sys.argv:record(True,'普通窗口测试，未嵌入桌面');raise SystemExit(0)
 ok,message=desktop_pin.pin(45);record(ok,message)
 if ok:mode_file.write_text(json.dumps({'mode':'kiosk-stable-v3'}),encoding='utf-8')
 else:raise SystemExit(1)

except Exception as error:
 record(False,str(error))
 raise SystemExit(1)
