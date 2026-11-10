"""Observe foreground fullscreen coverage without activating or changing any window."""
import ctypes,ctypes.wintypes as W,threading,time
import desktop_pin as d
active=False
u=d.u
class MonitorInfo(ctypes.Structure):_fields_=[('size',W.DWORD),('monitor',W.RECT),('work',W.RECT),('flags',W.DWORD)]
u.GetForegroundWindow.restype=W.HWND
u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
u.MonitorFromWindow.argtypes=[W.HWND,W.DWORD];u.MonitorFromWindow.restype=W.HANDLE
u.GetMonitorInfoW.argtypes=[W.HANDLE,ctypes.POINTER(MonitorInfo)]
u.IsIconic.argtypes=[W.HWND];u.IsIconic.restype=W.BOOL

def covers_monitor(bounds,monitor):
 l,t,r,b=bounds;ml,mt,mr,mb=monitor
 return r>l and b>t and l<=ml+2 and t<=mt+2 and r>=mr-2 and b>=mb-2

def detect():
 h=u.GetForegroundWindow()
 if not h or u.IsIconic(h):return False
 root=u.GetAncestor(h,2)
 if d.cls(root) in ('Progman','WorkerW','Shell_TrayWnd'):return False
 r=W.RECT();m=MonitorInfo();m.size=ctypes.sizeof(m)
 if not u.GetWindowRect(root,ctypes.byref(r)) or not u.GetMonitorInfoW(u.MonitorFromWindow(root,2),ctypes.byref(m)):return False
 if d.cls(root)=='Chrome_WidgetWin_1' and d.title(root).startswith('桌面陪伴 · 演示版') and d.proc_name(root)=='msedge.exe':return False
 return covers_monitor((r.left,r.top,r.right,r.bottom),(m.monitor.left,m.monitor.top,m.monitor.right,m.monitor.bottom))

def start(while_active=None):
 def monitor():
  global active
  while True:
   try:active=detect()
   except Exception:active=False
   if active and while_active is not None:while_active()
   time.sleep(1)
 threading.Thread(target=monitor,daemon=True,name='fullscreen-observer').start()
