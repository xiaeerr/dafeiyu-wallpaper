import ctypes, ctypes.wintypes, json, os, sys, time
u=ctypes.windll.user32;k=ctypes.windll.kernel32
try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
 try:u.SetProcessDPIAware()
 except Exception:pass
# Explicit pointer-size signatures keep desktop embedding reliable on 64-bit Windows.
from ctypes import wintypes as W
u.FindWindowW.argtypes=[W.LPCWSTR,W.LPCWSTR];u.FindWindowW.restype=W.HWND
u.FindWindowExW.argtypes=[W.HWND,W.HWND,W.LPCWSTR,W.LPCWSTR];u.FindWindowExW.restype=W.HWND
u.GetWindow.argtypes=[W.HWND,W.UINT];u.GetWindow.restype=W.HWND
u.SetParent.argtypes=[W.HWND,W.HWND];u.SetParent.restype=W.HWND
u.GetParent.argtypes=[W.HWND];u.GetParent.restype=W.HWND
u.GetWindowLongPtrW.argtypes=[W.HWND,ctypes.c_int];u.GetWindowLongPtrW.restype=ctypes.c_ssize_t
u.SetWindowLongPtrW.argtypes=[W.HWND,ctypes.c_int,ctypes.c_ssize_t];u.SetWindowLongPtrW.restype=ctypes.c_ssize_t
k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
k.CloseHandle.argtypes=[W.HANDLE]
u.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,ctypes.c_size_t,ctypes.c_ssize_t,W.UINT,W.UINT,ctypes.POINTER(ctypes.c_size_t)]
u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];u.GetClassNameW.restype=ctypes.c_int
u.GetWindowTextLengthW.argtypes=[W.HWND];u.GetWindowTextLengthW.restype=ctypes.c_int
u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];u.GetWindowTextW.restype=ctypes.c_int
u.IsWindowVisible.argtypes=[W.HWND];u.IsWindowVisible.restype=W.BOOL
u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)];u.GetWindowThreadProcessId.restype=W.DWORD
u.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT];u.SetWindowPos.restype=W.BOOL
u.ShowWindow.argtypes=[W.HWND,ctypes.c_int];u.ShowWindow.restype=W.BOOL
u.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetClientRect.restype=W.BOOL
u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];u.GetWindowRect.restype=W.BOOL
from data_paths import STATE
DATA=str(STATE)
STYLE_RECORD=os.path.join(DATA,'pin-style.json')
GWL_STYLE=-16
WS_CAPTION=0x00C00000;WS_THICKFRAME=0x00040000;WS_MINIMIZEBOX=0x00020000;WS_MAXIMIZEBOX=0x00010000;WS_SYSMENU=0x00080000;WS_POPUP=0x80000000
SWP_NOSIZE=0x0001;SWP_NOMOVE=0x0002;SWP_NOZORDER=0x0004;SWP_NOACTIVATE=0x0010;SWP_FRAMECHANGED=0x0020;SWP_SHOWWINDOW=0x0040
GW_CHILD=5;GW_HWNDNEXT=2
def _long(hwnd,style): 
 try:return u.GetWindowLongPtrW(hwnd,style)
 except AttributeError:return u.GetWindowLongW(hwnd,style)
def _set_long(hwnd,style,value):
 try:return u.SetWindowLongPtrW(hwnd,style,value)
 except AttributeError:return u.SetWindowLongW(hwnd,style,value)
def cls(h):
 b=ctypes.create_unicode_buffer(256);u.GetClassNameW(h,b,256);return b.value
def title(h):
 n=u.GetWindowTextLengthW(h)
 if n<=0:return ''
 b=ctypes.create_unicode_buffer(n+1);u.GetWindowTextW(h,b,n+1);return b.value
def proc_name(h):
 pid=ctypes.wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
 handle=k.OpenProcess(0x1000,False,pid.value)
 if not handle:return ''
 try:
  b=ctypes.create_unicode_buffer(512);sz=ctypes.wintypes.DWORD(512)
  if not k.QueryFullProcessImageNameW(handle,0,b,ctypes.byref(sz)):return ''
  return b.value.rsplit('\\',1)[-1].lower()
 finally:k.CloseHandle(handle)
def enum_top(cb):
 proto=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 probe=proto(cb);u.EnumWindows(probe,0);del probe
def find_edge():
 hit=[]
 def cb(h,l):
  if u.IsWindowVisible(h) and cls(h)=='Chrome_WidgetWin_1' and 'Dafeiyu Wallpaper' in title(h) and proc_name(h)=='msedge.exe':hit.append(h)
  return True
 enum_top(cb);return hit[0] if hit else None
def workerw_target():
 pm=u.FindWindowW('Progman',None)
 result=ctypes.c_size_t()
 u.SendMessageTimeoutW(pm,0x052C,0,0,0x0002,1000,ctypes.byref(result))
 # Windows 11 uses a visible WorkerW child of Progman. Hidden shell helper
 # WorkerWs must never be selected just because they have the same class name.
 candidates=[]
 def eligible(h):
  if cls(h)!='WorkerW' or not u.IsWindowVisible(h):return False
  r=ctypes.wintypes.RECT();u.GetClientRect(h,ctypes.byref(r))
  return r.right-r.left>=u.GetSystemMetrics(0)*.8 and r.bottom-r.top>=u.GetSystemMetrics(1)*.8
 child=u.GetWindow(pm,GW_CHILD)
 while child:
  if eligible(child):candidates.append(child)
  child=u.GetWindow(child,GW_HWNDNEXT)
 if candidates:return candidates[0]
 def cb(h,l):
  if u.FindWindowExW(h,None,'SHELLDLL_DefView',None):
   nxt=u.FindWindowExW(None,h,'WorkerW',None)
   if nxt and eligible(nxt):candidates.append(nxt)
  return True
 enum_top(cb)
 return candidates[0] if candidates else None
def pinned_hwnd():
 found=[];seen=set()
 def walk(p):
  if not p or p in seen:return
  seen.add(p);child=u.GetWindow(p,GW_CHILD);siblings=set()
  while child and child not in siblings:
   siblings.add(child)
   if cls(child)=='Chrome_WidgetWin_1' and 'Dafeiyu Wallpaper' in title(child) and proc_name(child)=='msedge.exe':found.append(child)
   if cls(child)=='WorkerW':walk(child)
   child=u.GetWindow(child,GW_HWNDNEXT)
 walk(u.FindWindowW('Progman',None))
 def cb(h,l):
  if cls(h)=='WorkerW':walk(h)
  return True
 enum_top(cb)
 return found[0] if found else None
def pin(timeout=15):
 deadline=time.time()+timeout
 hwnd=pinned_hwnd() or find_edge()
 while not hwnd and time.time()<deadline:
  time.sleep(.5);hwnd=pinned_hwnd() or find_edge()
 if not hwnd:return False,'没有找到大肥鱼窗口'
 w=workerw_target()
 while not w and time.time()<deadline:
  time.sleep(1);w=workerw_target()
 if not w:return False,'没有找到可见的全屏桌面壁纸层'
 style=_long(hwnd,GWL_STYLE)
 os.makedirs(DATA,exist_ok=True)
 if not os.path.exists(STYLE_RECORD):
  open(STYLE_RECORD,'w',encoding='utf-8').write(json.dumps({'style':style}))
 new=(style&~(WS_CAPTION|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX|WS_SYSMENU|WS_POPUP))|0x40000000
 _set_long(hwnd,GWL_STYLE,new)
 _set_long(hwnd,-20,_long(hwnd,-20)&~(0x100|0x200|0x20000))
 u.SetParent(hwnd,w)
 r=ctypes.wintypes.RECT();u.GetClientRect(w,ctypes.byref(r))
 u.SetWindowPos(hwnd,0,0,0,r.right-r.left,r.bottom-r.top,SWP_FRAMECHANGED|SWP_SHOWWINDOW|SWP_NOACTIVATE)
 u.ShowWindow(hwnd,5)
 # Crop browser-owned decoration outside the desktop host instead of using
 # Chromium kiosk/fullscreen, which can renegotiate its top-level state on resume.
 widget=u.FindWindowExW(hwnd,None,'Chrome_RenderWidgetHostHWND',None)
 for _ in range(5):
  if not widget:
   time.sleep(.15);widget=u.FindWindowExW(hwnd,None,'Chrome_RenderWidgetHostHWND',None);continue
  outer=ctypes.wintypes.RECT();content=ctypes.wintypes.RECT();parent=ctypes.wintypes.RECT()
  u.GetWindowRect(hwnd,ctypes.byref(outer));u.GetWindowRect(widget,ctypes.byref(content));u.GetWindowRect(w,ctypes.byref(parent))
  dx=content.left-parent.left;dy=content.top-parent.top
  dw=(parent.right-parent.left)-(content.right-content.left);dh=(parent.bottom-parent.top)-(content.bottom-content.top)
  if max(abs(dx),abs(dy),abs(dw),abs(dh))<=1:break
  u.SetWindowPos(hwnd,0,outer.left-parent.left-dx,outer.top-parent.top-dy,outer.right-outer.left+dw,outer.bottom-outer.top+dh,SWP_SHOWWINDOW|SWP_NOACTIVATE)
  time.sleep(.15)
 actual=ctypes.wintypes.RECT();u.GetWindowRect(widget or hwnd,ctypes.byref(actual));parent=ctypes.wintypes.RECT();u.GetWindowRect(w,ctypes.byref(parent))
 visible=bool(u.IsWindowVisible(hwnd)) and bool(u.IsWindowVisible(w))
 fitted=all(abs(a-b)<=2 for a,b in zip((actual.left,actual.top,actual.right,actual.bottom),(parent.left,parent.top,parent.right,parent.bottom)))
 if u.GetParent(hwnd)!=w or not visible or not fitted:return False,'桌面内容区尚未贴合，保留窗口供检查'
 return True,'已显示为全屏桌面壁纸'
def unpin():
 open(os.path.join(DATA,'desktop-session.json'),'w',encoding='utf-8').write(json.dumps({'enabled':False}))
 hwnd=pinned_hwnd()
 if not hwnd:hwnd=find_edge()
 if not hwnd:return False,'没有需要取消固定的窗口'
 u.SetParent(hwnd,None)
 try:style=json.loads(open(STYLE_RECORD,encoding='utf-8').read())['style']
 except Exception:style=0x16CF0000
 _set_long(hwnd,GWL_STYLE,style)
 u.SetWindowPos(hwnd,0,0,0,0,0,SWP_NOSIZE|SWP_NOMOVE|SWP_NOZORDER|SWP_FRAMECHANGED|SWP_SHOWWINDOW)
 u.ShowWindow(hwnd,3)
 return True,'已取消固定，恢复为普通窗口'
if __name__=='__main__':
 mode=sys.argv[1] if len(sys.argv)>1 else 'pin'
 ok,msg=(unpin() if mode=='unpin' else pin())
 print(msg)
