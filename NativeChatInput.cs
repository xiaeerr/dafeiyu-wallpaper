using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Native {
 [DllImport("user32.dll")] internal static extern bool SetProcessDpiAwarenessContext(IntPtr value);
 [DllImport("user32.dll")] internal static extern bool GetCaretPos(out Point p);
 [DllImport("user32.dll")] internal static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] internal static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] internal static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] internal static extern bool AttachThreadInput(uint thread,uint other,bool attach);
 [DllImport("kernel32.dll")] internal static extern uint GetCurrentThreadId();
 [DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] internal static extern IntPtr GetWindowLongPtr(IntPtr h,int index);
 [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] internal static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] internal static extern bool GetWindowRect(IntPtr h,out RECT r);
 [DllImport("dwmapi.dll", EntryPoint="DwmGetWindowAttribute")] internal static extern int Frame(IntPtr h,int a,out RECT r,int n);
 [DllImport("dwmapi.dll", EntryPoint="DwmGetWindowAttribute")] internal static extern int Cloak(IntPtr h,int a,out int v,int n);
 internal delegate bool EnumProc(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] internal static extern bool EnumWindows(EnumProc fn,IntPtr p);
 [DllImport("imm32.dll")] internal static extern IntPtr ImmGetContext(IntPtr h);
 [DllImport("imm32.dll")] internal static extern bool ImmReleaseContext(IntPtr h,IntPtr c);
 [DllImport("imm32.dll")] internal static extern bool ImmSetCandidateWindow(IntPtr c,ref Candidate f);
 [StructLayout(LayoutKind.Sequential)] internal struct RECT { public int l,t,r,b; internal Rectangle Box { get { return Rectangle.FromLTRB(l,t,r,b); } } }
 [StructLayout(LayoutKind.Sequential)] internal struct Candidate { public int index,style; public Point position; public RECT area; }
}
internal sealed class ChatEdit : TextBox {
 internal Action Submit;
 internal Func<bool> PasteImage;
 bool composing, swallowReturn, swallowPaste;
 protected override void WndProc(ref Message m) {
  if(m.Msg==0x100)swallowPaste=false;
  if(m.Msg==0x102 && m.WParam.ToInt32()==22 && swallowPaste){swallowPaste=false;return;}
  if(!composing && (m.Msg==0x302 || (m.Msg==0x100 && m.WParam.ToInt32()==86 && ModifierKeys==Keys.Control))) {
   if(PasteImage!=null && PasteImage()){swallowPaste=m.Msg==0x100;return;}
  }
  if(m.Msg==0x10D) composing=true;
  if(m.Msg==0x100) {
   swallowReturn=false;
   if(m.WParam.ToInt32()==13 && !composing && ModifierKeys==Keys.None) {
    swallowReturn=true; if(Submit!=null) Submit(); return;
   }
   if(m.WParam.ToInt32()==65 && ModifierKeys==Keys.Control) { SelectAll(); return; }
  }
  if(m.Msg==0x102 && m.WParam.ToInt32()==13 && swallowReturn) { swallowReturn=false; return; }
  base.WndProc(ref m);
  if(m.Msg==0x10E || m.Msg==0x8) composing=false;
  if((m.Msg==0x10D || m.Msg==0x10F || (m.Msg==0x282 && m.WParam.ToInt64()==5)) && composing && Focused) {
   Point caret;
   if(!Native.GetCaretPos(out caret)) return;
   var ctx=Native.ImmGetContext(Handle);
   if(ctx==IntPtr.Zero) return;
   try {
    var f=new Native.Candidate{style=0x80,position=caret,area=new Native.RECT{l=caret.X,t=caret.Y,r=caret.X+2,b=caret.Y+Font.Height}};
    Native.ImmSetCandidateWindow(ctx,ref f);
   } finally { Native.ImmReleaseContext(Handle,ctx); }
  }
 }
}
internal sealed class InputForm : Form {
 readonly ChatEdit edit=new ChatEdit();
 readonly Panel editSurface=new Panel();
 readonly Button send=new Button();
 readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();
 readonly JavaScriptSerializer json=new JavaScriptSerializer();
 static readonly string DataDir=Environment.GetEnvironmentVariable("DAFEIYU_STATE_DIR") ??
  Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),".dafeiyu-wallpaper-release");
 internal static readonly string Port=Environment.GetEnvironmentVariable("DAFEIYU_PORT") ?? "18766";
 readonly string token;
 readonly bool diagnostic;
 readonly uint pid=(uint)System.Diagnostics.Process.GetCurrentProcess().Id;
 long focusSeen=-1;
 bool polling,sending,dragPreview,attaching;
 DateTime dropUntil=DateTime.MinValue;
 const int MaxImageBytes=20*1024*1024;
 string regionKey="";
 DateTime lastGood=DateTime.UtcNow;
 readonly string statusFile=Path.Combine(DataDir,"native-input-status.json");
 DateTime lastStatus=DateTime.MinValue;
 internal InputForm(bool diag) {
  diagnostic=diag;
  token=File.ReadAllText(Path.Combine(DataDir,"bridge-token.txt")).Trim();
  Text="大肥鱼内嵌输入"; FormBorderStyle=diag?FormBorderStyle.Sizable:FormBorderStyle.None;
  ShowInTaskbar=diag;TopMost=true;StartPosition=FormStartPosition.Manual;
  BackColor=Color.Fuchsia;TransparencyKey=BackColor;Opacity=0.67;
  Color fill=Color.FromArgb(140,155,166), ink=Color.FromArgb(249,251,253);
  edit.Multiline=true; edit.AcceptsReturn=true;edit.MaxLength=600;edit.BorderStyle=BorderStyle.None;
  edit.Font=new Font("Microsoft YaHei UI",9.75f);edit.BackColor=fill;edit.ForeColor=ink;
  edit.Submit=SubmitText;edit.PasteImage=PasteImage;edit.ImeMode=ImeMode.NoControl;
  foreach(Control control in new Control[]{edit,editSurface,send}) {
   control.AllowDrop=true;
   control.DragEnter+=OfferImageDrop;
   control.DragOver+=OfferImageDrop;
   control.DragDrop+=DropImage;
  }
  editSurface.BackColor=fill;editSurface.Controls.Add(edit);
  send.Text="发送";send.BackColor=fill;send.ForeColor=ink;send.FlatStyle=FlatStyle.Flat;send.FlatAppearance.BorderSize=0;
  send.UseVisualStyleBackColor=false;send.FlatAppearance.MouseOverBackColor=Color.FromArgb(147,160,170);
  send.Click+=(o,e)=>SubmitText();
  Controls.Add(editSurface);Controls.Add(send);
  Deactivate+=(o,e)=>{if(!diagnostic)Hide();};
  Bounds=new Rectangle(40,40,450,100);
  if(diagnostic)LayoutInput(Bounds,new Rectangle(40,40,376,100),new Rectangle(423,40,67,100),8,8);
  timer.Interval=100;timer.Tick+=async(o,e)=>await Poll();
 }
 protected override CreateParams CreateParams { get {var p=base.CreateParams;if(!diagnostic)p.ExStyle|=0x80;return p;} }
 protected override bool ShowWithoutActivation {get {return dragPreview;}}
 internal void Start(){ if(diagnostic)Show(); timer.Start(); }
 void LayoutInput(Rectangle bounds,Rectangle input,Rectangle button,int padX,int padY) {
  input.Offset(-bounds.X,-bounds.Y);button.Offset(-bounds.X,-bounds.Y);
  editSurface.Bounds=input;send.Bounds=button;
  edit.SetBounds(padX,padY,Math.Max(1,input.Width-2*padX),Math.Max(1,input.Height-2*padY));
 }
 string Request(string path,string body,bool typing=false,byte[] image=null) {
  var r=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+Port+path);
  r.Proxy=null;r.Timeout=1600;r.ReadWriteTimeout=1600;r.Headers.Add("X-Wallpaper-Token",token);
  if(path=="/desktop/status"&&!diagnostic)r.Headers.Add("X-Dafeiyu-Typing",typing?"1":"0");
  if(body!=null||image!=null) {
   var bytes=image??Encoding.UTF8.GetBytes(body);r.Method="POST";
   r.ContentType=image==null?"application/json":"application/octet-stream";
   r.ContentLength=bytes.Length;
   using(var s=r.GetRequestStream())s.Write(bytes,0,bytes.Length);
  }
  using(var response=r.GetResponse())using(var reader=new StreamReader(response.GetResponseStream(),Encoding.UTF8))return reader.ReadToEnd();
 }
 static string FindImageFile(string[] paths) {
  if(paths==null)return null;
  foreach(string path in paths) {
   if(Regex.IsMatch(Path.GetExtension(path),@"^\.(png|jpe?g|gif|webp|bmp|avif|ico|tiff?)$",RegexOptions.IgnoreCase))
    return path;
  }
  return null;
 }
 static byte[] ReadImageFile(string path) {
  var info=new FileInfo(path);
  if(info.Length>MaxImageBytes)throw new IOException("图片不能超过 20 MB");
  return File.ReadAllBytes(path);
 }
 void OfferImageDrop(object sender,DragEventArgs args) {
  bool allowed=args.Data!=null&&args.Data.GetDataPresent(DataFormats.FileDrop);
  args.Effect=allowed?DragDropEffects.Copy:DragDropEffects.None;
  if(allowed)dropUntil=DateTime.UtcNow.AddMilliseconds(450);
 }
 void DropImage(object sender,DragEventArgs args) {
  string path=FindImageFile(args.Data.GetData(DataFormats.FileDrop) as string[]);
  dropUntil=DateTime.MinValue;
  if(path==null){send.Text="图片无效";return;}
  AttachImage(()=>ReadImageFile(path));
 }
 bool PasteImage() {
  try {
   if(Clipboard.ContainsFileDropList()){
    var entries=Clipboard.GetFileDropList();
    var paths=new string[entries.Count];entries.CopyTo(paths,0);
    var path=FindImageFile(paths);
    if(path!=null){AttachImage(()=>ReadImageFile(path));return true;}
   }
   if(!Clipboard.ContainsImage())return false;
   using(var bitmap=Clipboard.GetImage())
   using(var stream=new MemoryStream()) {
    if(bitmap==null)return false;
    bitmap.Save(stream,ImageFormat.Png);
    var bytes=stream.ToArray();
    AttachImage(()=>bytes);
    return true;
   }
  }catch(ExternalException){return false;}
 }
 async void AttachImage(Func<byte[]> read) {
  if(attaching||sending)return;
  attaching=true;send.Enabled=false;send.Text="载入…";
  try{await Task.Run(()=>Request("/desktop/attach",null,image:read()));send.Text="发送";}
  catch{send.Text="图片无效";}
  finally{attaching=false;send.Enabled=true;}
 }
 async void SubmitText() {
  if(sending||attaching)return;
  string draft=edit.Text;
  var payload=json.Serialize(new{message=draft.Trim()});
  sending=true;send.Enabled=false;send.Text="…";
  try{await Task.Run(()=>Request("/desktop/submit",payload));if(edit.Text==draft)edit.Clear();send.Text="发送";}
  catch{send.Text="重试";}
  finally{sending=false;send.Enabled=true;}
 }
 static Dictionary<string,object> Dict(object v){return (Dictionary<string,object>)v;}
 static bool Flag(Dictionary<string,object> v,string key){object x;return v.TryGetValue(key,out x)&&x is bool&&(bool)x;}
 List<Rectangle> Covering(Rectangle bounds) {
  var cuts=new List<Rectangle>();
  Native.EnumWindows((h,p)=>{
   if(!Native.IsWindowVisible(h)||Native.IsIconic(h))return true;
   uint owner;Native.GetWindowThreadProcessId(h,out owner);if(owner==pid)return true;
   var name=new StringBuilder(128);Native.GetClassName(h,name,128);string c=name.ToString();
   if(c=="Progman"||c=="WorkerW"||c=="IME"||c=="MSCTFIME UI"||c.IndexOf("Candidate",StringComparison.OrdinalIgnoreCase)>=0)return true;
   int cloaked;if(Native.Cloak(h,14,out cloaked,4)==0&&cloaked!=0)return true;
   Native.RECT rect;
   if(Native.Frame(h,9,out rect,16)!=0&&!Native.GetWindowRect(h,out rect))return true;
   long style=Native.GetWindowLongPtr(h,-20).ToInt64();
   // Cursor overlays and passive full-screen OSD hosts do not obscure desktop input.
   if((style&0x20)!=0 || ((style&0x08080000)==0x08080000 && h!=Native.GetForegroundWindow() && Rectangle.Inflate(rect.Box,2,2).Contains(Screen.FromRectangle(bounds).Bounds)))return true;
   var cut=Rectangle.Intersect(bounds,rect.Box);
   if(cut.Width>0&&cut.Height>0)cuts.Add(cut);
   return true;
  },IntPtr.Zero);
  return cuts;
 }
 void Place(Rectangle bounds,Rectangle input,Rectangle button,int padX,int padY,bool refreshClip,bool wanted) {
  bool moved=Bounds!=bounds;
  if(moved)Bounds=bounds;
  LayoutInput(bounds,input,button,padX,padY);
  // An idle editor never sits above other apps. Clip only when opening or relocating it.
  if(refreshClip||moved||!Visible) {
   var cuts=Covering(bounds);
   string key=bounds.ToString()+string.Join(";",cuts);
   if(key!=regionKey) {
    var clip=new Region(new Rectangle(Point.Empty,bounds.Size));
    foreach(var cut in cuts){var local=cut;local.Offset(-bounds.X,-bounds.Y);clip.Exclude(local);}
    bool exposed;using(var g=CreateGraphics())exposed=!clip.IsEmpty(g);
    var old=Region;Region=exposed?clip:null;if(old!=null)old.Dispose();if(!exposed)clip.Dispose();
    regionKey=key;hasExposure=exposed;
   }
  }
  if(!hasExposure){if(Visible)Hide();return;}
  if(!Visible)Show();
  if(wanted) {
   Activate();
   if(Native.GetForegroundWindow()!=Handle) {
    uint pid;
    uint foreground=Native.GetWindowThreadProcessId(Native.GetForegroundWindow(),out pid), thread=Native.GetCurrentThreadId();
    if(foreground!=0&&foreground!=thread&&Native.AttachThreadInput(thread,foreground,true)) {
     try { Native.SetForegroundWindow(Handle);edit.Focus(); }
     finally { Native.AttachThreadInput(thread,foreground,false); }
    }
   }
   if(Native.GetForegroundWindow()==Handle)edit.Focus();
  }
 }
 bool hasExposure;
 static Rectangle ScreenRect(Dictionary<string,object> item,Rectangle screen,double sx,double sy) {
  double x=Convert.ToDouble(item["x"]),y=Convert.ToDouble(item["y"]);
  double w=Convert.ToDouble(item["w"]),h=Convert.ToDouble(item["h"]);
  return Rectangle.FromLTRB(screen.Left+(int)Math.Round(x*sx),screen.Top+(int)Math.Round(y*sy),
                            screen.Left+(int)Math.Round((x+w)*sx),screen.Top+(int)Math.Round((y+h)*sy));
 }
 void ReportStatus(Rectangle bounds,Rectangle input,Rectangle button) {
  if((DateTime.UtcNow-lastStatus).TotalSeconds<1)return;
  lastStatus=DateTime.UtcNow;
  File.WriteAllText(statusFile,json.Serialize(new{visible=Visible,focus=Visible&&edit.Focused,hasDraft=edit.TextLength>0,
   rect=new[]{bounds.X,bounds.Y,bounds.Width,bounds.Height},input=new[]{input.X,input.Y,input.Width,input.Height},
   send=new[]{button.X,button.Y,button.Width,button.Height},backend="win32-edit"}));
 }
 async Task Poll() {
  if(polling)return;polling=true;
  try {
   bool typing=Visible&&Native.GetForegroundWindow()==Handle&&edit.Focused;
   var raw=await Task.Run(()=>Request("/desktop/status",null,typing));
   var data=Dict(json.DeserializeObject(raw));var state=Dict(data["state"]);
   lastGood=DateTime.UtcNow;
   if(diagnostic)return;
   long request=Convert.ToInt64(state["focusRequest"]);bool wanted=focusSeen>=0&&request>focusSeen;focusSeen=request;
   if(Flag(data,"fullscreen")||Flag(state,"memoryOpen")||Flag(state,"settingsOpen")||Flag(state,"chatSettingsOpen")||!state.ContainsKey("targets")) {
    if(Visible)Hide();ReportStatus(Rectangle.Empty,Rectangle.Empty,Rectangle.Empty);return;
   }
   Rectangle input=Rectangle.Empty,button=Rectangle.Empty;
   var view=(object[])data["viewport"];var screen=Screen.PrimaryScreen.Bounds;
   double sx=screen.Width/Convert.ToDouble(view[0]),sy=screen.Height/Convert.ToDouble(view[1]);
   foreach(var target in (object[])state["targets"]) {
    var item=Dict(target);string id=(string)item["id"];
    if(id=="fishInput")input=ScreenRect(item,screen,sx,sy);
    if(id=="fishSend")button=ScreenRect(item,screen,sx,sy);
   }
   bool available=input.Width>0&&input.Height>0&&button.Width>0&&button.Height>0;
   var bounds=available?Rectangle.Union(input,button):Rectangle.Empty;
   if(Flag(state,"dropInput"))dropUntil=DateTime.UtcNow.AddMilliseconds(450);
   bool focused=Visible&&Native.GetForegroundWindow()==Handle;
   bool wasPreview=dragPreview;
   dragPreview=!wanted&&!focused&&DateTime.UtcNow<dropUntil;
   if(available&&(wanted||focused||dragPreview)) {
    if(dragPreview&&!wasPreview)regionKey="";
    Place(bounds,input,button,(int)Math.Round(8*sx),(int)Math.Round(8*sy),wanted||dragPreview&&!wasPreview, wanted);
   } else if(Visible)Hide();
   ReportStatus(bounds,input,button);
  } catch { if(!diagnostic&&Visible&&(DateTime.UtcNow-lastGood).TotalSeconds>3)Hide(); }
  finally {polling=false;}
 }
 [STAThread] static void Main(string[] args) {
  try{Native.SetProcessDpiAwarenessContext(new IntPtr(-4));}catch(EntryPointNotFoundException){}
  bool first;
  using(var mutex=new Mutex(true,@"Local\DafeiyuNativeInputRelease"+InputForm.Port,out first)) {
   if(!first)return;
   Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
   using(var form=new InputForm(Array.IndexOf(args,"--diagnose-input")>=0)){form.FormClosed+=(o,e)=>Application.ExitThread();form.Start();Application.Run();}
  }
 }
}
