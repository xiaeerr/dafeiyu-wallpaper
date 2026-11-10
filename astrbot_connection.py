"""Discover only the configured AstrBot instance, including launcher-assigned ports."""
import json,os,threading,time,urllib.request,urllib.error
from contextlib import contextmanager
from pathlib import Path
import psutil
from data_paths import ASTRBOT_CORE
CORE=ASTRBOT_CORE
EXPECTED=(CORE/'main.py').resolve()
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
state={'ready':False,'message':'正在寻找 AstrBot','port':None}

def discover():
 for proc in psutil.process_iter(['name','cmdline']):
  try:
   if not (proc.info['name'] or '').lower().startswith('python'):continue
   if not any(Path(arg).resolve()==EXPECTED for arg in (proc.info['cmdline'] or [])[1:] if arg.endswith('main.py')):continue
   env=proc.environ()
   cfg=json.loads((CORE/'data'/'cmd_config.json').read_text(encoding='utf-8-sig'))
   port=int(env.get('DASHBOARD_PORT') or env.get('ASTRBOT_DASHBOARD_PORT') or cfg.get('dashboard',{}).get('port',6185))
   if not 1<=port<=65535:continue
   if any(c.status==psutil.CONN_LISTEN and c.laddr.port==port for c in proc.net_connections(kind='tcp')):return port
  except (psutil.Error,OSError,ValueError):continue
 return None

def endpoint():
 port=discover()
 if port is None:raise ConnectionError('AstrBot 尚未启动或正在恢复，连接会自动重试')
 return 'http://127.0.0.1:'+str(port)

@contextmanager
def local_api(scope):
 """Use the explicitly configured maintenance key for plugin and file operations."""
 token=os.environ.get('DAFEIYU_ASTRBOT_MAINTENANCE_KEY')
 if not token:
  raise PermissionError(f'Configure an AstrBot API key with {scope} scope in DAFEIYU_ASTRBOT_MAINTENANCE_KEY.')
 base=endpoint()+'/api/v1'
 def request(path,body=None,method='GET',raw=None,content_type=None):
  data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
  req=urllib.request.Request(base+path,method=method,data=data,
                             headers={'Authorization':'Bearer '+token,'Content-Type':content_type or 'application/json'})
  with http.open(req,timeout=50) as response:return json.load(response)
 yield request

def check(key,session):
 global state
 port=discover()
 current={'ready':False,'port':port,'message':'等待 AstrBot 启动或恢复'}
 if not key:current['message']='请先设置 AstrBot 密钥'
 elif port:
  try:
   req=urllib.request.Request(f'http://127.0.0.1:{port}/api/v1/chat/sessions/{session}?page_size=1',headers={'Authorization':'Bearer '+key})
   with http.open(req,timeout=3) as res:res.read(1)
   current.update(ready=True,message='已连接 AstrBot')
  except urllib.error.HTTPError as e:current['message']='AstrBot 密钥失效，请重新设置' if e.code in (401,403) else 'AstrBot 正在恢复，稍后自动重连'
  except (OSError,ValueError):current['message']='AstrBot 正在恢复，稍后自动重连'
 state=current
 return dict(state)

def start(get_key,session):
 def monitor():
  while True:
   try:check(get_key(),session)
   except Exception:
    global state
    state={'ready':False,'port':None,'message':'等待 AstrBot 恢复，正在重连'}
   time.sleep(5)
 threading.Thread(target=monitor,daemon=True,name='astrbot-reconnect').start()
