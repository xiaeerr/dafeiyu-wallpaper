"""Route mouse input to this application's desktop child, only in its UI regions.
No keyboard hooks and no input logging. Other applications and taskbar are excluded.
"""
import ctypes,ctypes.wintypes as W,queue,threading,time,uuid
import pythoncom
import desktop_pin
u=ctypes.windll.user32;k=ctypes.windll.kernel32
class Point(ctypes.Structure):_fields_=[('x',W.LONG),('y',W.LONG)]
class MouseInfo(ctypes.Structure):_fields_=[('pt',Point),('mouseData',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',ctypes.c_size_t)]
PROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,W.WPARAM,W.LPARAM)
u.SetWindowsHookExW.argtypes=[ctypes.c_int,PROC,W.HINSTANCE,W.DWORD];u.SetWindowsHookExW.restype=W.HHOOK
u.CallNextHookEx.argtypes=[W.HHOOK,ctypes.c_int,W.WPARAM,W.LPARAM];u.CallNextHookEx.restype=ctypes.c_ssize_t
u.WindowFromPoint.argtypes=[Point];u.WindowFromPoint.restype=W.HWND
u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
u.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
u.ScreenToClient.argtypes=[W.HWND,ctypes.POINTER(Point)]
u.SetFocus.argtypes=[W.HWND];u.SetFocus.restype=W.HWND
u.SetForegroundWindow.argtypes=[W.HWND];u.SetForegroundWindow.restype=W.BOOL
u.GetForegroundWindow.restype=W.HWND
u.AttachThreadInput.argtypes=[W.DWORD,W.DWORD,W.BOOL]
k.GetCurrentThreadId.restype=W.DWORD
regions=[];wheel_regions=[];viewport=(1,1);updated=0;state={};captured=False;events=queue.Queue(maxsize=128);hook=None;callback=None
cache=(0,None,None)
focus_request=0;native_capture=False
passthrough_press=None
icons_dirty_at=0
icon_snapshot=(0,None)

class ChildVariant(ctypes.Structure):
 """MSAA child IDs are VT_I4 values in a Windows VARIANT."""
 _fields_=[('type',ctypes.c_ushort),('reserved',ctypes.c_ushort*3),
           ('value',W.LONG),('padding',ctypes.c_byte*(12 if ctypes.sizeof(ctypes.c_void_p)==8 else 4))]

oleacc=ctypes.WinDLL('oleacc')
oleacc.AccessibleObjectFromWindow.argtypes=[W.HWND,W.DWORD,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
oleacc.AccessibleChildren.argtypes=[ctypes.c_void_p,W.LONG,W.LONG,ctypes.POINTER(ChildVariant),ctypes.POINTER(W.LONG)]
variant_clear=ctypes.OleDLL('oleaut32').VariantClear
variant_clear.argtypes=[ctypes.POINTER(ChildVariant)]
accessible_id=(ctypes.c_byte*16).from_buffer_copy(uuid.UUID('618736e0-3c3d-11cf-810c-00aa00389b71').bytes_le)

def desktop_icons():
 """Read icon rectangles from Explorer without sending it mouse events."""
 hosts=[u.FindWindowW('Progman',None)]
 def collect(h,_):
  if desktop_pin.cls(h)=='WorkerW':hosts.append(h)
  return True
 desktop_pin.enum_top(collect)
 for host in hosts:
  view=u.FindWindowExW(host,None,'SHELLDLL_DefView',None) if host else None
  if view:break
 else:return None
 items=u.FindWindowExW(view,None,'SysListView32',None)
 if not items:return None
 if not u.IsWindowVisible(items):return ()
 obj=ctypes.c_void_p()
 if oleacc.AccessibleObjectFromWindow(items,0xfffffffc,ctypes.byref(accessible_id),ctypes.byref(obj))!=0 or not obj:
  return None
 vtable=ctypes.cast(obj,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
 release=ctypes.WINFUNCTYPE(ctypes.c_ulong,ctypes.c_void_p)(vtable[2])
 count=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,ctypes.POINTER(W.LONG))(vtable[8])
 locate=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*([ctypes.POINTER(W.LONG)]*4),ChildVariant)(vtable[22])
 try:
  total=W.LONG()
  if count(obj,ctypes.byref(total))!=0:return None
  if total.value<=0:return ()
  children=(ChildVariant*total.value)()
  obtained=W.LONG()
  try:
   result=oleacc.AccessibleChildren(obj,0,total.value,children,ctypes.byref(obtained))
   if result<0:return None
   boxes=[]
   for child in children[:obtained.value]:
    # Desktop list items are integer children. Other accessible objects
    # (such as the list's scroll bar) are returned as IDispatch pointers.
    if child.type!=3:continue
    x,y,w,h=[W.LONG() for _ in range(4)]
    if locate(obj,ctypes.byref(x),ctypes.byref(y),ctypes.byref(w),ctypes.byref(h),child)!=0:
     return None
    if w.value>0 and h.value>0:boxes.append((x.value,y.value,x.value+w.value,y.value+h.value))
   return tuple(boxes)
  finally:
   for child in children[:obtained.value]:variant_clear(ctypes.byref(child))
 finally:release(obj)

def monitor_icons():
 global icon_snapshot
 pythoncom.CoInitialize()
 try:
  while True:
   started=time.perf_counter_ns()
   try:icon_snapshot=(started,desktop_icons())
   except Exception:icon_snapshot=(started,None)
   time.sleep(.2)
 finally:pythoncom.CoUninitialize()

def shell_has_priority(pt):
 at,boxes=icon_snapshot
 if boxes is None or at<=icons_dirty_at or time.perf_counter_ns()-at>1_000_000_000:
  return True
 return any(left<=pt.x<right and top<=pt.y<bottom for left,top,right,bottom in boxes)
def clean_regions(rects):
 clean=[]
 for r in rects[:128]:
  vals=[float(r[n]) for n in ('x','y','w','h')]
  if all(abs(v)<20000 for v in vals) and vals[2]>0 and vals[3]>0:clean.append(vals)
 return clean
def update(data):
 global regions,wheel_regions,viewport,updated,state
 vw=float(data['width']);vh=float(data['height'])
 if not (100<=vw<=20000 and 100<=vh<=20000):raise ValueError()
 clean=clean_regions(data.get('regions',[]))
 scroll=clean_regions(data.get('wheelRegions',data.get('regions',[])))
 regions=clean;wheel_regions=scroll;viewport=(vw,vh);updated=time.monotonic();state=data.get('state',{})
def target():
 global cache
 now=time.monotonic()
 if now-cache[0]<1:return cache[1:]
 h=desktop_pin.pinned_hwnd();widget=u.FindWindowExW(h,None,'Chrome_RenderWidgetHostHWND',None) if h else None
 cache=(now,h,widget);return h,widget
def desktop_point(pt):
 h=u.WindowFromPoint(pt);root=u.GetAncestor(h,2)
 return desktop_pin.cls(root) in ('Progman','WorkerW')
def in_region(pt,wheel=False):
 if time.monotonic()-updated>10:return False
 x=pt.x*viewport[0]/u.GetSystemMetrics(0);y=pt.y*viewport[1]/u.GetSystemMetrics(1)
 return any(rx<=x<=rx+rw and ry<=y<=ry+rh for rx,ry,rw,rh in (wheel_regions if wheel else regions))
def pointer_snapshot():
 pt=Point()
 if not u.GetCursorPos(ctypes.byref(pt)):return {'x':-1,'y':-1,'over':False}
 width=u.GetSystemMetrics(0);height=u.GetSystemMetrics(1)
 return {'x':pt.x/width,'y':pt.y/height,
         'over':in_region(pt) and desktop_point(pt) and not shell_has_priority(pt)}
def worker():
 while True:
  msg,pt,delta,buttons=events.get();h,widget=target()
  if not widget:continue
  p=Point(pt.x,pt.y)
  if msg==0x20A:
   lp=(p.x&65535)|((p.y&65535)<<16);wp=(delta&65535)<<16
  else:
   u.ScreenToClient(widget,ctypes.byref(p));lp=(p.x&65535)|((p.y&65535)<<16);wp=buttons
  u.PostMessageW(widget,msg,wp,lp)
def run():
 global callback,hook,captured
 @PROC
 def cb(code,msg,param):
  global captured,focus_request,native_capture,passthrough_press,icons_dirty_at
  try:
   if code>=0 and msg in (0x200,0x201,0x202,0x20A):
    info=ctypes.cast(param,ctypes.POINTER(MouseInfo)).contents
    if msg==0x202 and native_capture:
     native_capture=False;return 1
    if passthrough_press:
     if msg==0x202:
      if passthrough_press=='desktop':icons_dirty_at=time.perf_counter_ns()
      passthrough_press=None
     return u.CallNextHookEx(hook,code,msg,param)
    # Explorer owns passive pointer motion. Posting it to Chromium as well
    # makes Windows and the renderer alternate hover state and cursor shape.
    if msg==0x200 and not captured:
     return u.CallNextHookEx(hook,code,msg,param)
    hit_region=in_region(info.pt,wheel=msg==0x20A)
    on_desktop=desktop_point(info.pt)
    if not captured and on_desktop and shell_has_priority(info.pt):
     if msg==0x201:passthrough_press='desktop'
     return u.CallNextHookEx(hook,code,msg,param)
    if captured and not on_desktop:
     captured=False
     try:events.put_nowait((0x202,Point(info.pt.x,info.pt.y),0,0))
     except queue.Full:pass
    if msg==0x202 and not captured:
     return u.CallNextHookEx(hook,code,msg,param)
    if msg==0x201 and on_desktop:
     x=info.pt.x*viewport[0]/u.GetSystemMetrics(0);y=info.pt.y*viewport[1]/u.GetSystemMetrics(1)
     targets={t.get('id'):t for t in state.get('targets',[])}
     field=targets.get('fishInput',targets.get('fishForm'))
     input_blocked=any(state.get(flag) for flag in ('memoryOpen','settingsOpen','chatSettingsOpen'))
     if field and field['w']>0 and field['h']>0 and not input_blocked and field['x']<=x<=field['x']+field['w'] and field['y']<=y<=field['y']+field['h']:
      focus_request=time.monotonic_ns();native_capture=True;return 1
    own=on_desktop and hit_region
    # Leave a drag that began in another window entirely with Windows until release.
    if msg==0x201 and not own:passthrough_press='desktop' if on_desktop else 'window'
    # Never enumerate windows or inspect the renderer inside the global mouse hook.
    if captured or own:
     if msg==0x201:captured=True
     was_captured=captured
     if msg==0x202:captured=False
     try:events.put_nowait((msg,Point(info.pt.x,info.pt.y),ctypes.c_short(info.mouseData>>16).value,1 if captured and msg!=0x202 else 0))
     except queue.Full:pass
     if msg!=0x200 and (own or was_captured):return 1
  except Exception:captured=False
  return u.CallNextHookEx(hook,code,msg,param)
 callback=cb;hook=u.SetWindowsHookExW(14,callback,None,0)
 if not hook:return
 m=W.MSG()
 while u.GetMessageW(ctypes.byref(m),None,0,0)>0:u.TranslateMessage(ctypes.byref(m));u.DispatchMessageW(ctypes.byref(m))
def start():
 threading.Thread(target=monitor_icons,daemon=True,name='desktop-icon-bounds').start()
 threading.Thread(target=worker,daemon=True,name='wallpaper-mouse-dispatch').start()
 threading.Thread(target=run,daemon=True,name='wallpaper-desktop-input').start()
