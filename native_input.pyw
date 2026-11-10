"""Borderless native IME surface aligned exactly with the wallpaper chat form."""
import ctypes,ctypes.wintypes as W,json,re,threading,time,tkinter as tk,urllib.request,sys
DIAGNOSTIC="--diagnose-input" in sys.argv
from pathlib import Path
try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:pass
u=ctypes.windll.user32;u.GetForegroundWindow.restype=W.HWND;u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND;u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];u.SetForegroundWindow.argtypes=[W.HWND];u.SetWindowLongPtrW.argtypes=[W.HWND,ctypes.c_int,ctypes.c_ssize_t];u.GetWindowLongPtrW.argtypes=[W.HWND,ctypes.c_int];u.GetWindowLongPtrW.restype=ctypes.c_ssize_t
u.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
from data_paths import ORIGIN, PORT, STATE, TOKEN_FILE
token=TOKEN_FILE.read_text(encoding='ascii').strip()
def request(path,payload=None):
 data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
 req=urllib.request.Request(ORIGIN+path,data=data,headers={'Content-Type':'application/json','X-Wallpaper-Token':token})
 with urllib.request.urlopen(req,timeout=2) as res:return json.load(res)
k=ctypes.windll.kernel32;k.CreateMutexW.argtypes=[ctypes.c_void_p,W.BOOL,W.LPCWSTR];k.CreateMutexW.restype=W.HANDLE
mutex=k.CreateMutexW(None,False,f'Local\\DafeiyuNativeInputRelease{PORT}')
if k.GetLastError()==183:raise SystemExit(0)
r=tk.Tk();r.withdraw();r.overrideredirect(not DIAGNOSTIC);r.title('大肥鱼内嵌输入');r.configure(bg='#ff00ff');r.attributes('-topmost',True);r.attributes('-alpha',.67);r.attributes('-transparentcolor','#ff00ff')
t=tk.Text(r,wrap='word',width=1,height=2,font=('Microsoft YaHei UI',10),bg='#8c9ba6',fg='#f9fbfd',insertbackground='white',relief='flat',borderwidth=0,padx=8,pady=8,undo=True)
b=tk.Button(r,text='发送',font=('Microsoft YaHei UI',10),bg='#8c9ba6',fg='#f9fbfd',activebackground='#93a0aa',relief='flat',borderwidth=0,width=5)
r.update_idletasks();hwnd=u.GetAncestor(r.winfo_id(),2);u.SetWindowLongPtrW(hwnd,-20,u.GetWindowLongPtrW(hwnd,-20)|(0 if DIAGNOSTIC else 0x80))
state={};last_good=0;stop=False;sending=False;focus_seen=None;rect=None;last_status=0

def poll():
 global state,last_good,stop
 failures=0
 while not stop:
  try:state=request('/desktop/status');last_good=time.monotonic();failures=0
  except Exception:
   failures+=1
   # Resume/network hiccups must not permanently terminate the input surface.
   time.sleep(min(3,failures*.2))
  time.sleep(.15)
def done(ok):
 global sending
 sending=False;b.config(state='normal',text='发送' if ok else '重试')
 if ok:t.delete('1.0','end')
def send(event=None):
 global sending
 if event is not None and event.state&1:return
 # IME composition is handled by the native Windows text control.
 im=ctypes.windll.imm32;im.ImmGetContext.argtypes=[W.HWND];im.ImmGetContext.restype=W.HANDLE;im.ImmGetCompositionStringW.argtypes=[W.HANDLE,W.DWORD,ctypes.c_void_p,W.DWORD];im.ImmReleaseContext.argtypes=[W.HWND,W.HANDLE]
 context=im.ImmGetContext(t.winfo_id())
 try:
  if context and im.ImmGetCompositionStringW(context,8,None,0)>0:return
 finally:
  if context:im.ImmReleaseContext(t.winfo_id(),context)
 text=t.get('1.0','end-1c').strip()
 if not text or sending:return 'break'
 if len(text)>600:b.config(text='太长');return 'break'
 sending=True;b.config(state='disabled',text='…')
 def work():
  try:request('/desktop/submit',{'message':text});ok=True
  except Exception:ok=False
  try:r.after(1200,lambda:done(ok))
  except Exception:pass
 threading.Thread(target=work,daemon=True).start();return 'break'
t.bind('<Return>',send);b.config(command=send)
def tick():
 global rect,focus_seen,last_status
 if stop:r.destroy();return
 try:
  s=state.get('state',{});targets={x['id']:x for x in s.get('targets',[])};form=targets['fishForm'];vw,vh=state['viewport'];fg=u.GetForegroundWindow();name=ctypes.create_unicode_buffer(128);u.GetClassNameW(fg,name,128)
  req=s.get('focusRequest',0)
  if focus_seen is None:focus_seen=req
  wanted=req>focus_seen
  focus_seen=req
  blocked=state.get('fullscreen') or any(s.get(flag) for flag in ('memoryOpen','settingsOpen','chatSettingsOpen'))
  visible=time.monotonic()-last_good<3 and form['w']>0 and form['h']>0 and not blocked and (fg==hwnd or wanted)
  if DIAGNOSTIC:visible=True
  if visible:
   sx=u.GetSystemMetrics(0)/vw;sy=u.GetSystemMetrics(1)/vh
   def physical(box):
    left,top=round(box['x']*sx),round(box['y']*sy)
    return left,top,round((box['x']+box['w'])*sx)-left,round((box['y']+box['h'])*sy)-top
   new=physical(form)
   if new!=rect:r.geometry(f'{new[2]}x{new[3]}+{new[0]}+{new[1]}');rect=new
   for widget,target in ((t,'fishInput'),(b,'fishSend')):
    x,y,w,h=physical(targets[target]);widget.place(x=x-new[0],y=y-new[1],width=w,height=h)
   if r.state()=='withdrawn':r.deiconify();r.update_idletasks();u.SetWindowPos(hwnd,-1,*new,0x0010|0x0040)
   if wanted:
    u.SetForegroundWindow(hwnd);t.focus_set()
  else:r.withdraw()
  if time.monotonic()-last_status>1:
   last_status=time.monotonic()
   (STATE/'native-input-status.json').write_text(json.dumps({'visible':r.state()!='withdrawn','focus':r.focus_get()==t,'rect':rect,'foreground':name.value,'focusRequest':req}),encoding='utf-8')
 except Exception as error:
  r.withdraw()
  (STATE/'native-input-status.json').write_text(json.dumps({'error':str(error)}),encoding='utf-8')
 r.after(100,tick)
threading.Thread(target=poll,daemon=True).start();tick();r.mainloop()
