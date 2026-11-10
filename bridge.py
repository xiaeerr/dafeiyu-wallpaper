import ctypes, ctypes.wintypes, hashlib, json, os, re, secrets, sqlite3, threading, time, urllib.request, urllib.error, urllib.parse, uuid, webbrowser, subprocess, sys, mimetypes, base64, io
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import OrderedDict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
import memory_map
import astrbot_connection
import desktop_input
import fullscreen_state
import local_voice
memory_lock=threading.Lock()
voice_lock=threading.Lock()
voice_slots=threading.BoundedSemaphore(2)
voice_cache=OrderedDict()
input_active_until=0.0
input_commands=__import__("queue").Queue(maxsize=10)
from data_paths import STATE, PROFILES, PORT, ORIGIN, TOKEN_FILE, edge_executable
DATA=STATE; DATA.mkdir(exist_ok=True)
CHAT_SETTINGS=DATA/'chat-settings.json'
chat_settings_lock=threading.Lock()
CHAT_SWITCHES={'fish.actions','fish.idle','fish.autoScreen','fish.voice','fish.ownVoice'}
CHAT_INTERVALS={'fish.actionRepeatCd':(0,3600),'fish.idleCd':(30,7200),'fish.screenCd':(60,7200)}
WALLPAPER_SWITCHES={
 'showNodeInfo','showRootEnvironment','showConsole','showClock','avoidTaskbar','showParticles',
 'mouseTracking','enablePet','enablePinch','showChatter','mealEffects','showMusic','musicMotion','musicEffects',
}
WALLPAPER_RANGES={
 'characterScale':(75,120),'brightness':(45,115),'motion':(0,100),'fps':(15,60),
 'systemInterval':(2,60),'studyMinutes':(1,120),'chatterInterval':(15,180),'musicSensitivity':(50,150),
}
def bridge_token():
 try:
  with TOKEN_FILE.open('x',encoding='ascii') as file:
   file.write(secrets.token_urlsafe(32))
 except FileExistsError:pass
 token=TOKEN_FILE.read_text(encoding='ascii').strip()
 if len(token)<32:raise RuntimeError('Invalid local bridge token')
 return token
TOKEN=bridge_token()
MINIMAX_SETTINGS=DATA/'minimax-voice.bin'
COSYVOICE_SETTINGS=DATA/'cosyvoice-voice.bin'
MINIMAX_HOSTS={'cn':'api.minimaxi.com','global':'api.minimax.io'}
MINIMAX_TUNING={'speed':(float,1.0,0.5,2.0),'pitch':(int,0,-12,12),'timbre':(int,0,-100,100)}
VOICE_PREVIEW='你回来啦？我在这儿呢。今天累不累？要不要先歇一会儿。'
class Blob(ctypes.Structure): _fields_=[('cbData',ctypes.wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
def protect(data, decrypt=False):
 raw=ctypes.create_string_buffer(data); source=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte))); dest=Blob()
 fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
 if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest)): raise ctypes.WinError()
 try:return ctypes.string_at(dest.pbData,dest.cbData)
 finally:ctypes.windll.kernel32.LocalFree(dest.pbData)
def read_key():
 try:return protect((DATA/'chat-key.bin').read_bytes(),True).decode('utf-8')
 except Exception:return None
def read_voice_settings(path):
 try:
  with path.open('rb') as file:
   version=os.fstat(file.fileno()).st_mtime_ns
   return json.loads(protect(file.read(),True)),version
 except FileNotFoundError:return {},0

def valid_chat_settings(settings):
 if not isinstance(settings,dict):raise ValueError('聊天设置格式无效')
 for key,value in settings.items():
  if key in CHAT_SWITCHES and type(value) is bool:continue
  if key in CHAT_INTERVALS and type(value) is int:
   minimum,maximum=CHAT_INTERVALS[key]
   if minimum<=value<=maximum:continue
  if key.startswith('wallpaper.'):
   name=key.removeprefix('wallpaper.')
   if name in WALLPAPER_SWITCHES and type(value) is bool:continue
   if name=='infoSide' and value in ('left','right'):continue
   if name in WALLPAPER_RANGES and type(value) in (int,float):
    minimum,maximum=WALLPAPER_RANGES[name]
    if minimum<=value<=maximum:continue
  raise ValueError('聊天设置值无效')
 return settings

def chat_settings(updates=None,migrate=False):
 with chat_settings_lock:
  try:current=valid_chat_settings(json.loads(CHAT_SETTINGS.read_text(encoding='utf-8')))
  except FileNotFoundError:current={}
  if updates is not None:
   updates=valid_chat_settings(updates)
   merged={**updates,**current} if migrate else {**current,**updates}
   if merged!=current:
    pending=CHAT_SETTINGS.with_suffix('.tmp')
    pending.write_text(json.dumps(merged),encoding='utf-8')
    pending.replace(CHAT_SETTINGS)
   return merged
  return current

def minimax_audio(text,settings):
 host=MINIMAX_HOSTS[settings['region']]
 payload={
  'model':'speech-2.8-hd','text':text,'stream':False,'output_format':'hex',
  'voice_setting':{'voice_id':settings['voice_id'],'speed':settings.get('speed',1.0),'pitch':settings.get('pitch',0)},
  'audio_setting':{'format':'mp3','sample_rate':32000,'bitrate':128000,'channel':1},
 }
 if settings.get('timbre',0):payload['voice_modify']={'timbre':settings['timbre']}
 data=json.dumps(payload).encode()
 req=urllib.request.Request(f'https://{host}/v1/t2a_v2',data=data,headers={
  'Authorization':'Bearer '+settings['api_key'],'Content-Type':'application/json',
 })
 try:
  with urllib.request.urlopen(req,timeout=25) as response:
   result=json.loads(response.read(12*1024*1024))
 except urllib.error.HTTPError as error:
  raise ValueError(f'MiniMax 请求失败（HTTP {error.code}），请检查密钥和账号地区') from None
 except OSError:
  raise ValueError('连接 MiniMax 失败，请稍后重试') from None
 status=(result.get('base_resp') or {}).get('status_code')
 if status!=0:
  code=f'（错误码 {status}）' if isinstance(status,int) else ''
  raise ValueError(f'MiniMax 合成失败{code}，请检查账号额度、地区和音色 ID')
 try:
  audio=bytes.fromhex(result['data']['audio'])
 except (KeyError,TypeError,ValueError):
  raise ValueError('MiniMax 返回的语音格式无效') from None
 if len(audio)<1000:raise ValueError('MiniMax 返回的语音为空')
 return audio

class NoVoiceRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None

cosy_http=urllib.request.build_opener(NoVoiceRedirect())
def cosyvoice_audio(text,settings):
 workspace=settings['workspace']
 body={'model':'cosyvoice-v3-flash','input':{
  'text':text,'voice':settings['voice_id'],'format':'mp3','sample_rate':24000}}
 req=urllib.request.Request(
  f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer',
  data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+settings['api_key'],'Content-Type':'application/json'})
 try:
  with cosy_http.open(req,timeout=16) as response:result=json.loads(response.read(512*1024))
  url=(result.get('output') or {}).get('audio',{}).get('url','')
  parts=urllib.parse.urlsplit(url)
  if parts.scheme not in ('http','https') or parts.username or parts.password or parts.port is not None or not re.fullmatch(
      r'[a-z0-9-]+\.oss-cn-beijing\.aliyuncs\.com',parts.hostname or ''):
   raise ValueError('CosyVoice 未返回可用的音频，请检查业务空间、额度和音色 ID')
  with cosy_http.open(parts._replace(scheme='https').geturl(),timeout=8) as response:
   audio=response.read(12*1024*1024+1)
 except urllib.error.HTTPError as error:
  raise ValueError(f'CosyVoice 请求失败（HTTP {error.code}），请检查北京业务空间、密钥和音色 ID') from None
 except OSError:
  raise ValueError('CosyVoice 连接失败，请稍后重试') from None
 if not 1000<=len(audio)<=12*1024*1024 or not (audio.startswith(b'ID3') or audio[0]==255):
  raise ValueError('CosyVoice 返回的 MP3 无效')
 return audio

VOICE_PROVIDERS={
 'minimax':(MINIMAX_SETTINGS,'female-shaonv',minimax_audio),
 'cosyvoice':(COSYVOICE_SETTINGS,'longanhuan',cosyvoice_audio),
}

def delete_diary(source_id,version,backup_dir):
 path=Path(memory_map.DATA)/'plugin_data'/'astrbot_plugin_lijian'/'lijian.sqlite3'
 with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=5)) as db, db:
  db.row_factory=sqlite3.Row
  db.execute('PRAGMA foreign_keys=ON')
  db.execute('BEGIN IMMEDIATE')
  note=db.execute("SELECT * FROM notes WHERE id=? AND kind='diary' AND archived=0",(source_id,)).fetchone()
  if note is None or hashlib.sha256((note['body_md'] or note['title'] or '').strip().encode()).hexdigest()!=version:
   return False
  (backup_dir/(str(time.time_ns())+'.json')).write_text(json.dumps(dict(note),ensure_ascii=False,indent=2),encoding='utf-8')
  db.execute('DELETE FROM notes WHERE id=?',(source_id,))
  return True
key=read_key()
session_path=DATA/'session.txt'
if session_path.exists(): session=session_path.read_text(encoding='ascii').strip()
else: session=str(uuid.uuid4());session_path.write_text(session,encoding='ascii')
lock=threading.Lock(); input_process=None; inline_process=None
auto_screen_lock=threading.Lock();last_auto_screen=0.0
history_lock=threading.Lock()
history_path=DATA/'chat-history.json'
history_seconds=24*60*60
try:
 saved_history=json.loads(history_path.read_text(encoding='utf-8'))
 messages=[{**item,'at':item.get('at',history_path.stat().st_mtime)}
           for item in saved_history['messages']
           if isinstance(item,dict) and isinstance(item.get('role'),str)
           and isinstance(item.get('text'),str)
           and isinstance(item.get('at',0),(int,float))]
 revision=int(saved_history.get('revision',0))
except (OSError,ValueError,TypeError,KeyError):
 messages=[];revision=0
user32=ctypes.windll.user32; kernel32=ctypes.windll.kernel32
class POINT(ctypes.Structure): _fields_=[('x',ctypes.c_long),('y',ctypes.c_long)]
def win_text(h):
 n=user32.GetWindowTextLengthW(h)
 if n<=0:return ''
 buf=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(h,buf,n+1);return buf.value.strip()
def win_app(h):
 pid=ctypes.wintypes.DWORD();user32.GetWindowThreadProcessId(h,ctypes.byref(pid))
 handle=kernel32.OpenProcess(0x1000,False,pid.value)
 if not handle:return ''
 try:
  buf=ctypes.create_unicode_buffer(512);size=ctypes.wintypes.DWORD(512)
  if not kernel32.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):return ''
  return buf.value.rsplit('\\',1)[-1]
 finally:kernel32.CloseHandle(handle)
activity={'at':0.0,'windows':[]}
def activity_windows():
 now=time.time()
 if now-activity['at']<1:return activity['windows']
 found=[]
 enum=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 def collect(h,l):
  if user32.IsWindowVisible(h):
   t=win_text(h)
   if t and t not in ('Program Manager','Windows Input Experience'):
    found.append({'title':t[:100],'app':win_app(h) or '未知'})
  return True
 probe=enum(collect);user32.EnumWindows(probe,0);del probe
 activity['windows']=found[:14];activity['at']=now
 return activity['windows']
def cursor_snapshot():
 pt=POINT()
 if not user32.GetCursorPos(ctypes.byref(pt)):pt.x=pt.y=-1
 fg=user32.GetForegroundWindow()
 return {'x':pt.x,'y':pt.y,'screen':[user32.GetSystemMetrics(0),user32.GetSystemMetrics(1)],'foreground':{'title':win_text(fg)[:100],'app':win_app(fg) or '未知'},'windows':activity_windows()}

def desktop_voice_intent(message,data,streaming):
 if not data.get('automatic'):
  if re.search(r'(?:别|不要|不用|不想|禁止|不许).{0,5}(?:语音|念|读)|(?:用|只要|请发)文字',message):
   return 'text','declined'
  if re.search(r'发(?:个|一条|条|段)?语音|用语音|语音回复|念给我听|读给我听|说句话给我听',message):
   if streaming:return 'voice','requested'
 if streaming and data.get('allow_own_voice') is True:
  return 'choose','automatic' if data.get('auto_voice') is True else ''
 if streaming and data.get('auto_voice') is True:return 'text','automatic'
 return 'text',''

def upload_image(image):
 raw=base64.b64decode(image,validate=True)
 if len(raw)>5*1024*1024:raise ValueError('图片不能超过 5 MB')
 from PIL import Image
 with Image.open(io.BytesIO(raw)) as picture:
  picture.verify()
 boundary='----Dafeiyu'+secrets.token_hex(12)
 payload=(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="image.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()+raw+('\r\n--'+boundary+'--\r\n').encode())
 with astrbot_connection.local_api('file') as request:
  result=request('/file',method='POST',raw=payload,content_type='multipart/form-data; boundary='+boundary)
 attachment=(result.get('data') or {}) if isinstance(result,dict) else {}
 if not isinstance(attachment,dict) or not attachment.get('attachment_id'):raise ValueError('AstrBot 图片上传失败')
 return attachment['attachment_id']

def call_astrbot(message,on_delta=None,image=None,attachment_id=None):
 content=[{'type':'plain','text':message},{'type':'image','attachment_id':attachment_id or upload_image(image)}] if image or attachment_id else message
 body=json.dumps({'message':content,'session_id':session,'username':'wallpaper_companion','enable_streaming':True,**({'selected_provider':provider} if (provider:=os.getenv('DAFEIYU_ASTRBOT_PROVIDER')) else {}),'flags':{'enable_streaming':True,'enable_inline_genui':False,'enable_reasoning':False}}).encode()
 req=urllib.request.Request(astrbot_connection.endpoint()+'/api/v1/chat',data=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
 parts=[];pending=''
 with astrbot_connection.http.open(req,timeout=120) as res:
  if 'text/event-stream' not in res.headers.get('Content-Type',''):
   result=json.loads(res.read());raise ValueError(str(result.get('message') or result.get('msg') or '未返回聊天结果'))
  for raw in res:
   line=raw.decode('utf-8').strip()
   if not line.startswith('data:'):continue
   e=json.loads(line[5:].strip());t=e.get('type');v=e.get('data','')
   if t=='error':raise ValueError(str(v))
   if t=='plain' and e.get('chain_type') not in ('tool_call','tool_call_result','reasoning','think') and isinstance(v,str):
    if e.get('streaming'):
     pending+=v
     if on_delta:on_delta(v)
    else:
     if pending:parts.append(pending);pending=''
     parts.append(v)
   if t=='complete' and pending:parts.append(pending);pending=''
 raw=re.sub(r'&&[^&\n]{1,40}&&','', ''.join(parts)+pending)
 wants_voice=bool(re.search(r'(?:\[语音\]|【语音】)\s*$',raw))
 clean=re.sub(r'(?:\[语音\]|【语音】)\s*$','',raw)
 return clean.strip(),wants_voice
PAGE='''<!doctype html><meta charset="utf-8"><title>和大肥鱼聊天</title><style>body{font:16px/1.6 sans-serif;max-width:620px;margin:5vh auto;padding:0 15px;background:#202a32;color:#eef4f5}#history{height:45vh;overflow:auto;border:1px solid #768b95;padding:12px;background:#182128}p{white-space:pre-wrap;overflow-wrap:anywhere}input{box-sizing:border-box;padding:10px;width:100%;background:#121d24;color:white;border:1px solid #758994}button{padding:9px 16px;margin-top:8px}small{color:#bbcacf}</style><h2>♡ 和大肥鱼聊天</h2><p>这是壁纸的备用输入窗口。壁纸与这里显示相同的聊天内容。</p><div id="history"></div><form id="f"><input id="m" maxlength="600" placeholder="输入想说的话…" autocomplete="off"><button>发送</button></form><small id="status">连接中…</small><details><summary>连接设置</summary><p>填写 AstrBot 中仅有 chat 权限的密钥。密钥使用 Windows 当前账户加密保存在本机。</p><input id="key" type="password" placeholder="AstrBot API 密钥"><button id="save">保存密钥</button></details><script>const token=__TOKEN__;const headers={'Content-Type':'application/json','X-Wallpaper-Token':token};const log=document.getElementById('history'),status=document.getElementById('status');let rev=-1;async function refresh(){try{let d=await(await fetch('/history',{headers})).json();if(d.revision!==rev){rev=d.revision;log.replaceChildren();for(const item of d.messages){let p=document.createElement('p');p.textContent=item.role+'：'+item.text;log.appendChild(p)}log.scrollTop=log.scrollHeight}if(!status.dataset.busy)status.textContent=d.connection?.message||(d.ready?'已连接 AstrBot':'正在重连 AstrBot')}catch(e){status.textContent='连接程序未运行'}}document.getElementById('f').onsubmit=async e=>{e.preventDefault();let m=document.getElementById('m');if(!m.value.trim()||status.dataset.busy)return;let text=m.value.trim();m.value='';status.dataset.busy='1';status.textContent='大肥鱼正在想…';try{let r=await fetch('/chat',{method:'POST',headers,body:JSON.stringify({message:text,label:text})}),d=await r.json();if(!r.ok)throw Error(d.error);status.textContent='已回复'}catch(e){status.textContent='连接失败：'+e.message}finally{delete status.dataset.busy;refresh()}};document.getElementById('save').onclick=async()=>{let k=document.getElementById('key'),r=await fetch('/setup',{method:'POST',headers,body:JSON.stringify({key:k.value})});status.textContent=(await r.json()).message;k.value=''};refresh();setInterval(refresh,3000)</script>'''.replace('__TOKEN__',json.dumps(TOKEN))
def recording_path(reply_id):
 if isinstance(reply_id,str) and re.fullmatch(r'[a-f0-9]{32}',reply_id):
  directory=DATA/'voice-recordings'
  path=directory/(reply_id+'.audio')
  legacy=directory/(reply_id+'.mp3')
  return legacy if not path.exists() and legacy.exists() else path
 return None

def prune_history(now):
 cutoff=now-history_seconds
 before=len(messages)
 for item in messages:
  if item['at']<=cutoff and (path:=recording_path(item.get('reply_id'))):
   try:path.unlink(missing_ok=True)
   except OSError:pass
 messages[:]=[item for item in messages if item['at']>cutoff]
 return len(messages)!=before

def save_history():
 global revision
 revision+=1
 temp=history_path.with_suffix('.tmp')
 try:
  temp.write_text(json.dumps({'messages':messages,'revision':revision},ensure_ascii=False),encoding='utf-8')
  temp.replace(history_path)
 except OSError:
  pass  # Keep serving the in-memory history if the disk is temporarily unavailable.

def history_snapshot():
 with history_lock:
  if prune_history(time.time()):save_history()
  return {'messages':list(messages),'revision':revision}

def add(*entries,reply_id=None):
 with history_lock:
  now=time.time()
  prune_history(now)
  messages.extend({'role':role,'text':text,'at':now} for role,text in entries)
  if reply_id:messages[-1]['reply_id']=reply_id
  save_history()

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def setup(self):
  super().setup();self.connection.settimeout(15)
 def reply(self,status,data,cors=False):
  b=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
  if cors:self.send_header('Access-Control-Allow-Origin','null');self.send_header('Access-Control-Allow-Headers','Content-Type, X-Wallpaper-Token');self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
  self.end_headers();self.wfile.write(b)
 def authorized(self):
  origin=self.headers.get('Origin','');return origin in ('null',ORIGIN,'') and secrets.compare_digest(self.headers.get('X-Wallpaper-Token',''),TOKEN)
 def speak(self,data,cors):
  text=data.get('text') if isinstance(data,dict) else None
  if not isinstance(text,str) or not 0<len(text.strip())<=1800:
   self.reply(400,{'error':'这条消息无法朗读'},cors);return
  reply_id=data.get('reply_id')
  recording=recording_path(reply_id)
  if reply_id:
   with history_lock:
    entry=next((item for item in reversed(messages) if item.get('reply_id')==reply_id
                and item['at']>time.time()-history_seconds and item['role']=='大肥鱼' and item['text']==text),None)
   if not recording or not entry:
    self.reply(404,{'error':'找不到对应的回复'},cors);return
   try:
    self.send_audio(recording.read_bytes(),cors);return
   except FileNotFoundError:pass
   except OSError:
    self.reply(500,{'error':'无法读取语音记录'},cors);return
  core=astrbot_connection.CORE
  config=core/'data'/'config'/'astrbot_plugin_yuren_voice_config.json'
  worker=core/'data'/'plugins'/'astrbot_plugin_yuren_voice'/'speech.py'
  python=core.parent/'venv'/'Scripts'/'python.exe'
  try:
   provider=data.get('provider','default')
   if provider not in ('default','minimax'):
    self.reply(400,{'error':'未知的语音方案'},cors);return
   local_root,local_version=local_voice.read_config(DATA) if provider=='default' else (None,0)
   if local_root is not None:
    provider,version,settings,synthesize='feiyu',local_version,local_root,local_voice.synthesize
   else:
    for name in ('cosyvoice','minimax') if provider=='default' else ('minimax',):
     path,_,synthesize=VOICE_PROVIDERS[name]
     settings,version=read_voice_settings(path)
     if settings.get('enabled'):
      provider=name;break
    else:
     if provider=='minimax':
      self.reply(409,{'error':'请先在语音设置启用 MiniMax'},cors);return
     provider='edge'
   key=(text.strip(),provider,version) if provider!='edge' else (
    text.strip(),'edge',config.stat().st_mtime_ns,(core/'data'/'cmd_config.json').stat().st_mtime_ns)
   with voice_lock:
    audio=voice_cache.get(key)
    if audio is not None:voice_cache.move_to_end(key)
   if audio is None:
    if provider=='feiyu' and fullscreen_state.active:
     self.reply(409,{'error':'全屏时已暂停本机语音生成'},cors);return
    if not voice_slots.acquire(blocking=False):
     self.reply(429,{'error':'语音正在生成，请稍后再试'},cors);return
    try:
     if provider!='edge':audio=synthesize(key[0],settings)
     else:
      result=subprocess.run([str(python),str(worker)],input=key[0].encode(),capture_output=True,
                            timeout=28,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
      audio=result.stdout
    finally:
     voice_slots.release()
    if len(audio)<1000:
     self.reply(422,{'error':'这条消息没有可朗读的文字'},cors);return
    with voice_lock:
     voice_cache[key]=audio
     if len(voice_cache)>20:voice_cache.popitem(last=False)
  except local_voice.LocalVoiceError as error:
   self.reply(502,{'error':str(error)},cors);return
  except ValueError as error:
   self.reply(502,{'error':str(error) if str(error).startswith(('MiniMax','连接 MiniMax','CosyVoice')) else '无法读取语音设置'},cors);return
  except (OSError,subprocess.SubprocessError):
   self.reply(502,{'error':'语音合成暂时不可用'},cors);return
  if recording:
   try:
    recording.parent.mkdir(exist_ok=True)
    temp=recording.with_name(recording.stem+'.'+uuid.uuid4().hex+'.tmp')
    try:
     temp.write_bytes(audio)
     temp.replace(recording)
    finally:temp.unlink(missing_ok=True)
   except OSError:
    self.reply(500,{'error':'语音已生成，但无法保存本机录音'},cors);return
  self.send_audio(audio,cors)
 def send_audio(self,audio,cors=False):
  content_type='audio/wav' if audio[:4]==b'RIFF' and audio[8:12]==b'WAVE' else 'audio/mpeg'
  self.send_response(200);self.send_header('Content-Type',content_type)
  self.send_header('Content-Length',str(len(audio)));self.send_header('Cache-Control','no-store')
  if cors:self.send_header('Access-Control-Allow-Origin','null')
  self.end_headers()
  try:self.wfile.write(audio)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_OPTIONS(self):
  if self.headers.get('Origin')=='null':self.reply(200,{},True)
  else:self.reply(403,{})
 def do_GET(self):
  global input_active_until
  if self.headers.get('Host')!=f'127.0.0.1:{PORT}':self.send_error(403);return
  if self.path=="/health":self.reply(200,{"ok":True});return
  if self.path=='/chat/settings' and self.authorized():
   try:self.reply(200,chat_settings(),self.headers.get('Origin')=='null')
   except (OSError,ValueError):self.reply(500,{'error':'无法读取聊天设置'},self.headers.get('Origin')=='null')
   return
  if urllib.parse.urlsplit(self.path).path=='/history/voice' and self.authorized():
   reply_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('reply_id',[''])[0]
   path=recording_path(reply_id)
   with history_lock:
    available=path and any(item.get('reply_id')==reply_id and item.get('duration') and
                           item['at']>time.time()-history_seconds for item in messages)
   if available:
    try:self.send_audio(path.read_bytes(),self.headers.get('Origin')=='null');return
    except OSError:pass
   self.reply(404,{'error':'这条语音的本机录音已不可用'},self.headers.get('Origin')=='null');return
  if self.path=='/voice/settings' and self.authorized():
   try:
    result={'feiyu':{'enabled':local_voice.read_config(DATA)[0] is not None,'style':'cute'}}
    for provider,(path,voice,_) in VOICE_PROVIDERS.items():
     settings,_=read_voice_settings(path)
     result[provider]={'enabled':settings.get('enabled',False),'region':settings.get('region','cn'),
                       'workspace':settings.get('workspace',''),'voice_id':settings.get('voice_id',voice),
                       'has_key':bool(settings.get('api_key'))}
     if provider=='minimax':
      result[provider].update({k:settings.get(k,default) for k,(_,default,_,_) in MINIMAX_TUNING.items()})
   except (OSError,ValueError):
    self.reply(500,{'error':'无法读取本机语音设置'});return
   self.reply(200,result);return
  if self.path=='/memory/view':
   if self.headers.get('Sec-Fetch-Site')=='cross-site':self.send_error(403);return
   raw=memory_map.HTML.encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','SAMEORIGIN');self.end_headers();self.wfile.write(raw);return
  if self.path=='/desktop/commands' and self.authorized():
   commands=[]
   while not input_commands.empty():
    try:commands.append(input_commands.get_nowait())
    except __import__('queue').Empty:break
   self.reply(200,{'commands':commands,'typing':time.monotonic()<input_active_until});return
  if self.path=='/desktop/status' and self.authorized():
   typing=self.headers.get('X-Dafeiyu-Typing')
   if typing in ('0','1'):input_active_until=time.monotonic()+2 if typing=='1' else 0
   self.reply(200,{'hook':bool(desktop_input.hook),'regions':len(desktop_input.regions),'target':bool(desktop_input.cache[2]),'state':{**desktop_input.state,'focusRequest':desktop_input.focus_request},'viewport':desktop_input.viewport,'fullscreen':fullscreen_state.active});return
  if self.path=='/desktop/pointer' and self.authorized():
   self.reply(200,desktop_input.pointer_snapshot());return
  if self.path=='/memory/data':
   if not self.authorized():self.reply(403,{'error':'拒绝访问'});return
   try:
    with memory_lock:result=memory_map.scan_data()
    self.reply(200,result)
   except Exception:self.reply(500,{'error':'记忆读取失败'})
   return
  if self.path=='/app/bridge-token.js':
   if self.headers.get('Sec-Fetch-Site')=='cross-site':self.send_error(403);return
   raw=('window.WALLPAPER_BRIDGE_TOKEN='+json.dumps(TOKEN)+';').encode()
   self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8')
   self.send_header('Cache-Control','no-store');self.send_header('Cross-Origin-Resource-Policy','same-origin')
   self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if self.path.startswith('/app/'):
   if self.headers.get('Sec-Fetch-Site')=='cross-site':self.send_error(403);return
   rel=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path[5:]);target=(ROOT/rel).resolve()
   public_files={'index.html','app.js','audio-host.js','style.css','layout.css','astrbot-wallpaper.js','voice-settings.html'}
   public_asset=target.is_relative_to(ROOT/'assets') and target.suffix.lower() in {'.png','.ttf'}
   if not target.is_relative_to(ROOT) or not (rel in public_files or public_asset) or not target.is_file():
    self.send_error(404);return
   raw=target.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(raw)));self.send_header('Cross-Origin-Resource-Policy','same-origin');self.send_header('Cache-Control','no-cache');self.end_headers();self.wfile.write(raw);return
  if self.path=='/':
   b=PAGE.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b);return
  if self.path=='/cursor' and self.authorized():self.reply(200,cursor_snapshot(),self.headers.get('Origin')=='null');return
  if urllib.parse.urlsplit(self.path).path in ('/desktop/screenshot','/desktop/screenshot/auto') and self.authorized():
   try:
    if urllib.parse.urlsplit(self.path).path.endswith('/auto'):
     global last_auto_screen
     params=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
     seconds=int(params.get('interval',['300'])[0])
     if not 60<=seconds<=7200:raise ValueError('截图间隔无效')
     with auto_screen_lock:
      if time.monotonic()-last_auto_screen<seconds:
       self.reply(429,{'error':'主动截图间隔尚未结束'});return
      last_auto_screen=time.monotonic()
    from PIL import ImageGrab
    image=ImageGrab.grab(all_screens=True)
    image.thumbnail((1920,1080))
    output=io.BytesIO();image.convert('RGB').save(output,format='JPEG',quality=82)
    raw=output.getvalue()
    self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
   except Exception:self.reply(500,{'error':'桌面截图失败'});
   return
  if self.path=='/history' and self.authorized():self.reply(200,{**history_snapshot(),'ready':bool(key) and astrbot_connection.state['ready'],'connection':dict(astrbot_connection.state)},self.headers.get('Origin')=='null');return
  self.reply(403,{'error':'拒绝访问'})
 def do_POST(self):
  global key, input_process, inline_process, revision
  if self.headers.get('Host')!=f'127.0.0.1:{PORT}':self.send_error(403);return
  origin=self.headers.get('Origin',''); cors=origin=='null'
  if not self.authorized():self.reply(403,{'error':'来源或令牌无效'},cors);return
  try:
   n=int(self.headers.get('Content-Length','0'))
   limit=8*1024*1024 if self.path in ('/chat','/chat/stream') else (65536 if self.path in ('/memory/edit','/desktop/regions') else 8192)
   if n<=0 or n>limit:raise ValueError('请求大小无效')
   data=json.loads(self.rfile.read(n))
  except Exception:self.reply(400,{'error':'请求格式无效'},cors);return
  if self.path=='/chat/settings':
   try:
    if not isinstance(data,dict) or not isinstance(data.get('settings'),dict):raise ValueError()
    self.reply(200,chat_settings(data['settings'],data.get('migrate') is True),cors)
   except ValueError:self.reply(400,{'error':'聊天设置格式无效'},cors)
   except OSError:self.reply(500,{'error':'无法保存聊天设置'},cors)
   return
  if self.path=='/voice/speak':
   self.speak(data,cors);return
  if self.path=='/history/voice':
   reply_id=data.get('reply_id') if isinstance(data,dict) else None
   duration=data.get('duration') if isinstance(data,dict) else None
   path=recording_path(reply_id)
   if not path or type(duration) is not int or not 1<=duration<=3600 or not path.is_file():
    self.reply(400,{'error':'语音时长或录音无效'},cors);return
   with history_lock:
    entry=next((item for item in reversed(messages)
                if reply_id and item.get('reply_id')==reply_id and item['role']=='大肥鱼'),None)
    if entry is not None and not entry.get('duration'):
     entry['duration']=duration
     save_history()
   self.reply(200 if entry is not None else 404,{'ok':entry is not None},cors);return
  if self.path=='/voice/settings':
   if origin!=ORIGIN or not isinstance(data,dict):
    self.reply(403,{'error':'请从本机语音设置页面操作'});return
   try:
    provider=data.get('provider','minimax')
    if not isinstance(provider,str) or provider not in VOICE_PROVIDERS:
     self.reply(400,{'error':'未知的语音方案'});return
    path,_,synthesize=VOICE_PROVIDERS[provider]
    previous,_=read_voice_settings(path)
    mode=data.get('mode','test-and-save')
    if mode not in ('test-and-save','preview','save-tuning') or (mode=='save-tuning' and provider!='minimax'):
     self.reply(400,{'error':'未知的语音设置操作'});return
    if data.get('enabled') is False:
     settings={**previous,'enabled':False}
     audio=None
    else:
     region=data.get('region')
     workspace=data.get('workspace','')
     voice=data.get('voice_id')
     secret=data.get('api_key') or previous.get('api_key','')
     voice_pattern=r'[A-Za-z0-9_(). -]{1,256}' if provider=='minimax' else r'[A-Za-z0-9_-]{1,128}'
     if not isinstance(voice,str) or not voice.strip() or not re.fullmatch(voice_pattern,voice) or not isinstance(secret,str) or not re.fullmatch(r'[A-Za-z0-9._-]{8,2048}',secret):
      self.reply(400,{'error':'请检查 API Key 和音色 ID'});return
     settings={'enabled':True,'voice_id':voice,'api_key':secret}
     if provider=='minimax':
      if not isinstance(region,str) or region not in MINIMAX_HOSTS:
       self.reply(400,{'error':'请选择 MiniMax 账号地区'});return
      settings['region']=region
      for field,(parse,default,minimum,maximum) in MINIMAX_TUNING.items():
       try:
        value=parse(str(data.get(field,previous.get(field,default))))
        if not minimum<=value<=maximum:raise ValueError
       except (ValueError,TypeError):
        self.reply(400,{'error':'语速、音高或音色参数超出范围'});return
       settings[field]=value
     else:
      if not isinstance(workspace,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',workspace):
       self.reply(400,{'error':'请填写阿里云百炼北京地域业务空间 ID'});return
      settings['workspace']=workspace
     if mode=='save-tuning':
      if not previous.get('enabled') or any(settings[k]!=previous.get(k) for k in ('region','api_key')):
       self.reply(409,{'error':'更换密钥或地区后，请先试听并启用 MiniMax'});return
      audio=None
     else:
      audio=synthesize(VOICE_PREVIEW,settings)
      if mode=='preview':
       self.send_audio(audio);return
    with voice_lock:
     temp=path.with_suffix('.tmp')
     temp.write_bytes(protect(json.dumps(settings).encode()))
     temp.replace(path)
   except ValueError as error:
    self.reply(502,{'error':str(error) if str(error).startswith(('MiniMax','连接 MiniMax','CosyVoice')) else '无法读取语音设置'});return
   except OSError:
    self.reply(500,{'error':'无法保存本机语音设置'});return
   if audio is None:self.reply(200,{'ok':True});return
   self.send_audio(audio);return
  if self.path=='/memory/open':
   try:
    edge=edge_executable()
    subprocess.Popen([
     str(edge),'--app='+ORIGIN+'/memory/view',
     '--user-data-dir='+str(PROFILES/'memory-profile'),
     '--window-size=1200,800','--no-first-run','--disable-background-mode',
    ],creationflags=subprocess.CREATE_NO_WINDOW)
   except OSError:
    self.reply(500,{'error':'无法启动记忆星图窗口'},cors);return
   self.reply(200,{'ok':True},cors);return
  if self.path in ('/memory/edit','/memory/delete','/memory/archive'):
   try:
    with memory_lock:
     editing=self.path.endswith('/edit')
     archiving=self.path.endswith('/archive')
     if archiving and data.get('src')!='diary':
      self.reply(400,{'status':'error','message':'只有璃笺日记可以归档'});return
     value=str(data.get('new_text','')).strip()
     if editing and (not value or len(value)>10000):
      self.reply(400,{'status':'error','message':'记忆内容不能为空或超过10000字'});return
     if data.get('src') in ('diary','living'):
      source=data['src']
      node=next((node for node in memory_map.scan_data()['nodes']
                 if node['src']==source and node['id']==data.get('id') and node.get('source_id') is not None),None)
      if node is None or node.get('version')!=data.get('version'):
       self.reply(409,{'status':'error','message':'记忆已变化，请重新扫描'});return
      backup=DATA/'memory-backups';backup.mkdir(exist_ok=True)
      source_id=node['source_id']
      if source=='diary' and not editing and not archiving:
       if not delete_diary(source_id,data['version'],backup):
        self.reply(409,{'status':'error','message':'日记已变化，请重新扫描'});return
       self.reply(200,{'status':'ok'});return
      (backup/(str(time.time_ns())+'.json')).write_text(json.dumps(node,ensure_ascii=False,indent=2),encoding='utf-8')
      with astrbot_connection.local_api('plugin') as request:
       base='/plugins/extensions/'
       if source=='diary':
        path=base+'astrbot_plugin_lijian/notes/'+urllib.parse.quote(source_id,safe='')
        if editing:result=request(path,{'body_md':value},'PATCH')
        else:result=request(path,method='DELETE')
        details=result.get('data') or result
        ok=bool(details.get('note'))
       else:
        path=base+'astrbot_plugin_livingmemory/page/memories/'
        payload={'memory_id':source_id,'field':'content','value':value} if editing else {'memory_ids':[source_id]}
        result=request(path+('update' if editing else 'batch-delete'),payload,'POST')
        ok=result.get('status')=='ok' and (editing or result.get('data',{}).get('deleted_count')==1)
      if not ok:
       self.reply(502,{'status':'error','message':result.get('message') or '来源插件没有保存这次操作'});return
      self.reply(200,{'status':'ok'});return
     items=memory_map.load_core();hit=next((it for it in items if it.get('ts')==data.get('ts') and it.get('content')==data.get('old' if self.path.endswith('/edit') else 'content')),None)
     if hit is None:self.reply(404,{'status':'error','message':'记忆已变化，请重新扫描'});return
     backup=DATA/'memory-backups';backup.mkdir(exist_ok=True)
     import shutil
     shutil.copy2(memory_map.CORE_MEM,backup/(str(time.time_ns())+'.json'))
     if self.path.endswith('/edit'):
      hit['content']=value
      if data.get('new_level') in ('core','sub','min'):hit['level']=data['new_level']
     else:items.remove(hit)
     target=Path(memory_map.CORE_MEM);tmp=target.with_suffix('.wallpaper.tmp');tmp.write_text(json.dumps(items,ensure_ascii=False,indent=1),encoding='utf-8');tmp.replace(target)
    self.reply(200,{'status':'ok'})
   except Exception:self.reply(500,{'status':'error','message':'保存失败，原数据备份已保留'})
   return
  if self.path=='/desktop/focus-input':desktop_input.focus_request=time.monotonic_ns();self.reply(200,{'ok':True});return
  if self.path=='/desktop/submit':
   text=str(data.get('message','')).strip()
   if not text or len(text)>600:self.reply(400,{'error':'消息长度无效'});return
   try:input_commands.put_nowait(text);self.reply(200,{'ok':True})
   except __import__('queue').Full:self.reply(429,{'error':'请等待上一条消息'} )
   return
  if self.path=='/desktop/regions':
   try:desktop_input.update(data);self.reply(200,{'ok':True,'fullscreen':fullscreen_state.active})
   except Exception:self.reply(400,{'error':'区域无效'})
   return
  if self.path=='/setup':
   if origin!=ORIGIN:self.reply(403,{'error':'来源不允许'});return
   v=data.get('key','').strip()
   if not v:self.reply(400,{'message':'请输入密钥'});return
   try:(DATA/'chat-key.bin').write_bytes(protect(v.encode()));key=v;self.reply(200,{'message':'密钥已保存。请发送消息测试。'})
   except Exception:self.reply(500,{'message':'密钥保存失败'})
   return
  if self.path not in ('/chat','/chat/stream'):self.reply(404,{'error':'路径不存在'},cors);return
  streaming=self.path=='/chat/stream'
  if not key:self.reply(503,{'error':'请先填写 AstrBot 密钥'},cors);return
  emit=lambda obj:None
  if streaming:
   self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8');self.send_header('Cache-Control','no-store')
   if cors:self.send_header('Access-Control-Allow-Origin','null')
   self.end_headers()
   def emit(obj):
    try:self.wfile.write(('data: '+json.dumps(obj,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
    except Exception:pass
  if not lock.acquire(False):
   if streaming:emit({'error':'上一条消息尚未完成，请稍等片刻'})
   else:self.reply(429,{'error':'上一条消息尚未完成'},cors)
   return
  try:
   message=data.get('message','').strip();label=str(data.get('label','')).strip()
   image=data.get('image')
   if image is not None and (not isinstance(image,str) or len(image)>7*1024*1024):raise ValueError('图片大小无效')
   if not message or len(message)>600 or len(label)>600:raise ValueError('消息长度无效')
   if data.get('screen_decision'):
    if not data.get('automatic') or image:raise ValueError('截图决策请求无效')
    answer,_=call_astrbot(message)
    self.reply(200,{'look':answer.strip()=='[看桌面]'},cors)
    return
   entry=('互动' if data.get('automatic') else '我',label or message)
   allow_silence=bool(data.get('silent_ok'))
   attachment_id=upload_image(image) if image else None
   if attachment_id and streaming:emit({'image_received':True})
   if not allow_silence:add(entry)
   mode,voice_intent=desktop_voice_intent(message,data,streaming)
   voice_context=DATA/'voice-turn.json'
   voice_temp=voice_context.with_suffix('.tmp')
   try:
    voice_temp.write_text(json.dumps({'session':session,'mode':mode,'at':time.time(),
                                     'message_sha256':hashlib.sha256(message.encode()).hexdigest()}),encoding='utf-8')
    voice_temp.replace(voice_context)
   except OSError:pass
   try:
    reply,wants_voice=call_astrbot(message,(lambda v:emit({'delta':v})) if streaming else None,attachment_id=attachment_id)
   finally:
    try:voice_context.unlink(missing_ok=True)
    except OSError:pass
   if not reply:raise ValueError('AstrBot 没有返回可显示的文字')
   if reply=='[静默]' and data.get('silent_ok'):
    if streaming:emit({'done':True,'silent':True})
    else:self.reply(200,{'reply':''},cors)
   else:
    answer=('大肥鱼',reply[:1500])
    reply_id=uuid.uuid4().hex if streaming else None
    add(*((entry,answer) if allow_silence else (answer,)),reply_id=reply_id)
    result={'reply':answer[1],'reply_id':reply_id,
            'voice':('chosen' if mode=='choose' and wants_voice else voice_intent)}
    if streaming:emit({'done':True,**result})
    else:self.reply(200,result,cors)
  except urllib.error.HTTPError as e:
   if streaming:emit({'error':'AstrBot 返回 HTTP '+str(e.code)+'，请检查密钥'})
   else:self.reply(502,{'error':'AstrBot 返回 HTTP '+str(e.code)+'，请检查密钥'},cors)
  except (urllib.error.URLError,TimeoutError):
   if streaming:emit({'error':'AstrBot 暂时断开，正在自动重连，请稍后再发送'})
   else:self.reply(502,{'error':'AstrBot 暂时断开，正在自动重连，请稍后再发送'},cors)
  except Exception as e:
   if streaming:emit({'error':str(e)[:200]})
   else:self.reply(502,{'error':str(e)[:200]},cors)
  finally:lock.release()
if __name__=='__main__':
 import msvcrt,socket
 service_lock=open(DATA/'bridge.lock','a+b');service_lock.seek(0);service_lock.write(b'0');service_lock.flush();service_lock.seek(0)
 try:msvcrt.locking(service_lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:raise SystemExit(0)
 class ExclusiveServer(ThreadingHTTPServer):
  allow_reuse_address=False
  request_queue_size=64
  daemon_threads=True
  def server_bind(self):
   self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
   super().server_bind()
 server=ExclusiveServer(('127.0.0.1',PORT),Handler)
 astrbot_connection.start(lambda:key,session)
 desktop_input.start()
 fullscreen_state.start(local_voice.release_idle)
 import service_diagnostics
 service_diagnostics.start(DATA)
 native=ROOT/'NativeChatInput.exe'
 subprocess.Popen([str(native)] if native.exists() else [str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'native_input.pyw')],cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
 import desktop_lifecycle
 threading.Thread(target=desktop_lifecycle.guard,daemon=True,name='desktop-resume-guard').start()
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
