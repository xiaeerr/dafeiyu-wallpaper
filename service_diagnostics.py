"""Record thread stacks only if this service fails its own local health check."""
import faulthandler,threading,time,urllib.request

from data_paths import ORIGIN

def start(data):
 def monitor():
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));failures=0;last_dump=0
  while True:
   time.sleep(10)
   try:
    with opener.open(ORIGIN+'/health',timeout=3) as r:r.read(64)
    failures=0
   except Exception:
    failures+=1
    if failures>=2 and time.monotonic()-last_dump>60:
     last_dump=time.monotonic();p=data/'service-stall.log'
     try:
      if p.exists() and p.stat().st_size>200000:p.replace(data/'service-stall.previous.log')
      with p.open('a',encoding='utf-8') as f:
       f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' local health stalled\n');f.flush();faulthandler.dump_traceback(file=f,all_threads=True)
     except OSError:pass
 threading.Thread(target=monitor,daemon=True,name='local-service-health').start()
