(() => {
  'use strict';
  const query = new URLSearchParams(location.search);
  const demo = query.get('demo') === '1';
  const preview = demo || query.get('test') === '1';
  const pinned = query.get('desktop') === '1';
  if(pinned)document.documentElement.dataset.wallpaperPinned='';
  const root = document.createElement('section');
  root.id = 'astrChat';
  root.setAttribute('aria-label', '与大肥鱼聊天');
  root.innerHTML = `<div class="fish-chat-title"><span class="fish-move-grip" title="拖动聊天框">♡ 和大肥鱼说话</span><span class="fish-title-actions"><button id="fishDock" type="button" title="吸附回侧栏" aria-label="吸附回侧栏" hidden>↩</button><button id="fishSettingsButton" type="button" aria-label="打开聊天设置" aria-expanded="false">⚙</button><button id="fishToggle" type="button" aria-label="收起聊天">−</button></span></div>
    <div id="fishBody"><form id="fishForm"><textarea id="fishInput" rows="2" maxlength="600" placeholder="想说的话…（可拖入图片）" aria-label="聊天内容"></textarea><button id="fishSend" type="submit">发送</button></form><div class="fish-image-tools"><button id="fishAddImage" type="button">＋ 图片</button><button id="fishScreen" type="button">截图并发送</button><input id="fishImageFile" type="file" accept="image/*" hidden><div id="fishImagePreview" hidden><img alt="待发送图片"><button id="fishRemoveImage" type="button" aria-label="移除图片">×</button></div></div>
      <div id="fishHistory" role="log" aria-live="polite"><p class="fish-note">启动连接程序后，就可以和我聊天啦。</p></div><small id="fishStatus" role="status">等待连接</small><small id="fishVoiceStatus" role="status" hidden></small></div>
      <div id="fishSettingsOverlay" role="dialog" aria-label="聊天设置" hidden><div class="fish-settings-heading"><strong>聊天设置</strong><button id="fishSettingsClose" type="button" aria-label="关闭聊天设置">×</button></div><div class="fish-controls"><label><input id="fishActions" type="checkbox" checked> 动作回应</label><label><input id="fishIdle" type="checkbox"> 主动闲聊</label><span class="fish-voice-settings"><label><input id="fishVoice" type="checkbox"> 自动朗读</label><button id="fishOwnVoice" type="button" aria-label="允许她主动发语音" aria-pressed="false">主动语音 · 关</button></span></div>
      <div class="fish-tuning"><label>同动作间隔 <input id="fishActionCd" type="number" min="0" max="3600" step="1"> 秒</label><label>闲聊间隔 <input id="fishIdleCd" type="number" min="30" max="7200" step="10"> 秒</label></div><div class="fish-tuning"><label><input id="fishAutoScreen" type="checkbox"> 主动看桌面</label><label>看桌面间隔 <input id="fishScreenCd" type="number" min="60" max="7200" step="30"> 秒</label></div>
      <small id="fishSettingsSaveStatus" role="status"></small></div>${['top','right','bottom','left'].map(edge=>
        `<span class="fish-resize-grip" data-edge="${edge}" aria-hidden="true"></span>`).join('')}`;
  const dock=document.querySelector('.right-panel'), stage=document.getElementById('layoutStage');
  dock.appendChild(root);
  const $ = id => document.getElementById(id);
  const history = $('fishHistory'), status = $('fishStatus');
  const geometryKey='fish.chat.geometry';
  const normalizeReply=text=>text.replace(/&(?:nbsp(?:[;:]|(?![\w]))|#0*160;|#x0*a0;)/gi,' ');
  let floating=null, gesture=null, geometryFrame=0;
  const clamp=(n,min,max)=>Math.min(max,Math.max(min,n));
  const limits=()=>{
    const w=Math.max(1,stage.clientWidth-12),h=Math.max(1,stage.clientHeight-12);
    return {w,h,minW:Math.min(240,w),minH:Math.min(220,h)};
  };
  function placeChat(box,follow=false){
    const {w,h,minW,minH}=limits();
    const width=clamp(box.width,minW,w),height=clamp(box.height,minH,h);
    const x=clamp(box.x,6,6+w-width),y=clamp(box.y,6,6+h-height);
    const scroll=history.scrollTop, detached=!floating;
    if(!floating){stage.appendChild(root);root.classList.add('fish-floating');$('fishDock').hidden=false;}
    floating={x,y,width,height};
    for(const [key,value] of Object.entries({left:x,top:y,width,height}))root.style[key]=value+'px';
    if(follow||detached)history.scrollTop=follow?history.scrollHeight:scroll;
  }
  function saveGeometry(){
    try{if(floating)localStorage.setItem(geometryKey,JSON.stringify(floating));else localStorage.removeItem(geometryKey);}catch{}
  }
  function queueDesktopRegions(){requestAnimationFrame(desktopRegions);}
  try{
    const box=JSON.parse(localStorage.getItem(geometryKey));
    if(box&&['x','y','width','height'].every(key=>Number.isFinite(box[key])))placeChat(box);
  }catch{}
  $('fishDock').onclick=()=>{
    const scroll=history.scrollTop,follow=history.scrollHeight-history.clientHeight-scroll<=12;
    floating=null;
    root.classList.remove('fish-floating');
    for(const key of ['left','top','width','height'])root.style.removeProperty(key);
    dock.appendChild(root);
    $('fishDock').hidden=true;
    scheduleChatFit();
    history.scrollTop=follow?history.scrollHeight:scroll;
    saveGeometry();queueDesktopRegions();
  };
  function startGeometry(event,edge){
    if(event.button!==0||gesture)return;
    event.preventDefault();
    const r=root.getBoundingClientRect(),s=stage.getBoundingClientRect();
    const inward=!floating&&r.left+r.width/2>s.left+s.width/2;
    gesture={startX:event.clientX,startY:event.clientY,x:r.left-s.left,y:r.top-s.top,
      width:r.width,height:floating?.height??r.height,edge,inward,
      follow:history.scrollHeight-history.clientHeight-history.scrollTop<=12};
  }
  function moveGeometry(){
    geometryFrame=0;
    const g=gesture;
    if(!g||g.dx===undefined)return;
    const {dx,dy}=g;
    const horizontal=g.edge==='left'||g.edge==='right';
    const distance=g.edge?Math.abs(horizontal?dx:dy):Math.max(Math.abs(dx),Math.abs(dy));
    if(!g.moved&&distance<4)return;
    g.moved=true;
    if(!g.edge){
      const width=floating?.width??Math.max(limits().minW,g.width);
      const height=floating?.height??Math.max(limits().minH,g.height);
      placeChat({...g,width,height,x:g.x+dx-(g.inward?width-g.width:0),y:g.y+dy},g.follow);
      return;
    }
    const {w,h,minW,minH}=limits();
    const fromStart=g.edge==='left'||g.edge==='top';
    const origin=horizontal?g.x:g.y;
    const size=horizontal?g.width:g.height;
    const minimum=horizontal?minW:minH;
    const maximum=fromStart?origin+size-6:(horizontal?w:h)+6-origin;
    const change=(horizontal?dx:dy)*(fromStart?-1:1);
    const nextSize=clamp(size+change,minimum,Math.max(minimum,maximum));
    const nextOrigin=fromStart?origin+size-nextSize:origin;
    const box=horizontal?{...g,x:nextOrigin,width:nextSize}:{...g,y:nextOrigin,height:nextSize};
    placeChat(box,g.follow);
  }
  root.querySelector('.fish-chat-title').addEventListener('mousedown',event=>{
    if(!event.target.closest('button'))startGeometry(event,null);
  });
  for(const grip of root.querySelectorAll('.fish-resize-grip')){
    grip.addEventListener('mousedown',event=>startGeometry(event,grip.dataset.edge));
  }
  window.addEventListener('mousemove',e=>{
    if(!gesture||!(e.buttons&1))return;
    gesture.dx=e.clientX-gesture.startX;gesture.dy=e.clientY-gesture.startY;
    if(!geometryFrame)geometryFrame=requestAnimationFrame(moveGeometry);
  });
  function endGeometry(){
    if(!gesture)return;
    if(geometryFrame){cancelAnimationFrame(geometryFrame);moveGeometry();}
    if(gesture.moved){saveGeometry();queueDesktopRegions();}
    gesture=null;
  }
  window.addEventListener('mouseup',endGeometry);
  window.addEventListener('blur',endGeometry);
  new ResizeObserver(()=>{
    if(floating&&!gesture)placeChat(floating);
    scheduleChatFit();queueDesktopRegions();
  }).observe(stage);
  let fitFrame=0, lastPanelLimit=-1;
  function scheduleChatFit(){
    if(fitFrame)return;
    fitFrame=requestAnimationFrame(()=>{
      fitFrame=0;
      if(floating)return;
      const footer=$('clockPanel').getBoundingClientRect();
      const bottom=footer.height?footer.top:$('layoutStage').getBoundingClientRect().bottom;
      const limit=Math.max(62,Math.floor(bottom-root.getBoundingClientRect().top-8));
      if(limit===lastPanelLimit)return;
      lastPanelLimit=limit;
      root.style.setProperty('--fish-panel-max',limit+'px');
    });
  }
  window.addEventListener('resize',scheduleChatFit);
  const chatLayoutObserver=new ResizeObserver(scheduleChatFit);
  for(const section of [document.querySelector('.interaction-panel'),$('consolePanel'),$('clockPanel')])chatLayoutObserver.observe(section);
  scheduleChatFit();
  // The wallpaper host forwards mouse messages to the page. Use DOM
  // sliders so dragging does not depend on Chromium's native scrollbar.
  function addDragScrollbar(scroller, label){
    const wrapper=document.createElement('div');
    wrapper.className='fish-scroll-wrap';
    scroller.before(wrapper);
    wrapper.append(scroller);
    const rail=document.createElement('div');
    rail.className='fish-scroll-rail';
    rail.setAttribute('role','scrollbar');
    rail.setAttribute('aria-controls',scroller.id);
    rail.setAttribute('aria-label',label);
    rail.setAttribute('aria-orientation','vertical');
    rail.setAttribute('aria-valuemin','0');
    rail.tabIndex=0;
    const thumb=document.createElement('div');
    thumb.className='fish-scroll-thumb';
    rail.append(thumb);
    wrapper.append(rail);
    let grab=null,updateFrame=0;
    function metrics(){
      const height=rail.clientHeight;
      const max=Math.max(0,scroller.scrollHeight-scroller.clientHeight);
      const size=max?Math.min(height,Math.max(18,height*scroller.clientHeight/scroller.scrollHeight)):height;
      return {max,size,travel:height-size};
    }
    function update(){
      updateFrame=0;
      const {max,size,travel}=metrics();
      rail.setAttribute('aria-hidden',String(!max));
      rail.tabIndex=max?0:-1;
      thumb.style.height=size+'px';
      const position=Math.max(0,Math.min(max,scroller.scrollTop));
      thumb.style.transform=`translateY(${max?position/max*travel:0}px)`;
      rail.setAttribute('aria-valuemax',String(max));
      rail.setAttribute('aria-valuenow',String(Math.round(position)));
    }
    function scheduleUpdate(){if(!updateFrame)updateFrame=requestAnimationFrame(update);}
    function drag(y){
      const {max,travel}=metrics();
      if(travel<=0)return;
      const offset=Math.max(0,Math.min(travel,y-rail.getBoundingClientRect().top-grab));
      scroller.scrollTop=offset/travel*max;
    }
    rail.addEventListener('mousedown',event=>{
      if(event.button!==0)return;
      event.preventDefault();
      grab=event.target===thumb?event.clientY-thumb.getBoundingClientRect().top:metrics().size/2;
      drag(event.clientY);
    });
    window.addEventListener('mousemove',event=>{
      if(grab!==null&&(event.buttons&1))drag(event.clientY);
    });
    window.addEventListener('mouseup',()=>{grab=null;});
    window.addEventListener('blur',()=>{grab=null;});
    rail.addEventListener('keydown',event=>{
      const changes={ArrowUp:-30,ArrowDown:30,PageUp:-scroller.clientHeight,PageDown:scroller.clientHeight};
      if(event.key in changes){event.preventDefault();scroller.scrollTop+=changes[event.key];}
    });
    scroller.addEventListener('scroll',scheduleUpdate,{passive:true});
    const resizeObserver=new ResizeObserver(scheduleUpdate);
    resizeObserver.observe(scroller);
    resizeObserver.observe(rail);
    new MutationObserver(scheduleUpdate).observe(scroller,{childList:true,subtree:true});
    scheduleUpdate();
  }
  addDragScrollbar(history,'聊天记录滚动条');

  const editedSettings=new Set();
  let settingsQueue=Promise.resolve();
  const readStoredSetting=key=>{try{return localStorage.getItem(key);}catch{return null;}};
  const getPref=(key,fallback)=>{
    const value=readStoredSetting(key);
    return value===null?fallback:value==='1';
  };
  async function requestChatSettings(settings,migrate=false){
    const options={headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}};
    if(settings){
      options.method='POST';
      options.headers['Content-Type']='application/json';
      options.body=JSON.stringify({settings,migrate});
      options.keepalive=true;
    }
    const response=await fetch('/chat/settings',options);
    if(!response.ok)throw new Error('聊天设置无法保存或读取，请重试。');
    return response.json();
  }
  function queueSettingsSave(settings){
    settingsQueue=settingsQueue.then(async()=>{
      await requestChatSettings(settings);
      $('fishSettingsSaveStatus').textContent='';
    }).catch(error=>{$('fishSettingsSaveStatus').textContent=error.message;});
  }
  function savePref(key,value){
    editedSettings.add(key);
    try{localStorage.setItem(key,typeof value==='boolean'?(value?'1':'0'):String(value));}catch{}
    if(query.get('test')==='1')return;
    queueSettingsSave({[key]:value});
  }
  const autoVoice=$('fishVoice'), voiceStatus=$('fishVoiceStatus');
  const ownVoice=$('fishOwnVoice');
  let lastOwnVoice=0, ownVoiceEnabled=getPref('fish.ownVoice',false);
  function renderOwnVoice(){
    ownVoice.setAttribute('aria-pressed',String(ownVoiceEnabled));
    ownVoice.textContent=ownVoiceEnabled?'主动语音 · 开':'主动语音 · 关';
  }
  renderOwnVoice();
  ownVoice.onclick=()=>{
    ownVoiceEnabled=!ownVoiceEnabled;
    savePref('fish.ownVoice',ownVoiceEnabled);
    renderOwnVoice();
  };
  const voiceAudio=new Audio();
  let voiceJob=null, localVoice=false;
  const setDualVoice=enabled=>document.body.classList.toggle('fish-dual-voice',enabled);
  window.addEventListener('storage',event=>{if(event.key==='fish.voice.dual')setDualVoice(event.newValue==='true');});
  if(query.get('test')!=='1')fetch('/voice/settings',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}})
    .then(response=>response.ok?response.json():null)
    .then(settings=>{
      localVoice=Boolean(settings?.feiyu?.enabled);
      setDualVoice(Boolean((localVoice||settings?.cosyvoice?.enabled)&&settings?.minimax?.enabled));
    })
    .catch(()=>{});
  autoVoice.checked=getPref('fish.voice',false);
  autoVoice.onchange=()=>{
    savePref('fish.voice',autoVoice.checked);
    if(!autoVoice.checked&&voiceJob?.automatic&&!voiceJob.recordingId)stopVoice();
  };
  function voiceNotice(message=''){
    voiceStatus.textContent=message;
    voiceStatus.hidden=!message;
  }
  function setVoiceButton(button,state){
    if(!button)return;
    const icon=button.querySelector('.fish-voice-icon')||button;
    icon.textContent=state==='playing'?'■':state==='loading'?'…':button.dataset.voiceLabel;
    button.setAttribute('aria-pressed',String(Boolean(state)));
  }
  function stopVoice(){
    const job=voiceJob;
    voiceJob=null;
    if(!job)return;
    job.controller.abort();
    voiceAudio.pause();
    voiceAudio.removeAttribute('src');
    voiceAudio.load();
    if(job.url)URL.revokeObjectURL(job.url);
    setVoiceButton(job.button,'');
  }
  voiceAudio.addEventListener('ended',stopVoice);
  async function playVoice(text,button=null,automatic=false,provider='default',recordingId=null,replay=false){
    if(automatic&&voiceJob&&!voiceJob.automatic)return;
    const toggle=(button&&voiceJob?.button===button)||(replay&&voiceJob?.recordingId===recordingId);
    stopVoice();
    voiceNotice();
    if(toggle)return;
    const controller=new AbortController();
    const job={controller,button,automatic,recordingId,url:null};
    voiceJob=job;
    setVoiceButton(button,'loading');
    const timeout=setTimeout(()=>controller.abort(),localVoice&&provider==='default'&&!replay?132000:32000);
    try{
      const response=replay?await fetch('/history/voice?reply_id='+encodeURIComponent(recordingId),{
        headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},signal:controller.signal,
      }):await fetch('/voice/speak',{
        method:'POST',headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},
        body:JSON.stringify({text,provider,reply_id:recordingId}),signal:controller.signal,
      });
      if(!response.ok)throw Error((await response.json()).error||'语音播放失败');
      const audio=await response.blob();
      if(voiceJob!==job)return;
      job.url=URL.createObjectURL(audio);
      voiceAudio.src=job.url;
      await voiceAudio.play();
      if(voiceJob!==job)return false;
      setVoiceButton(job.button,'playing');
      return {duration:Number.isFinite(voiceAudio.duration)?Math.max(1,Math.ceil(voiceAudio.duration)):null};
    }catch(error){
      if(voiceJob!==job)return;
      stopVoice();
      voiceNotice(error.name==='AbortError'?'生成语音超时，请重试':error.name==='NotAllowedError'?'点击消息旁的扬声器播放':error.message);
    }finally{clearTimeout(timeout);}
  }
  function voiceButton(text,provider){
    const button=document.createElement('button');
    button.type='button';
    button.className='fish-voice-button';
    button.dataset.voiceLabel=provider==='minimax'?'HD':'🔊';
    button.textContent=button.dataset.voiceLabel;
    button.title=provider==='minimax'?'用 MiniMax HD 朗读这条消息':'朗读这条消息';
    if(provider==='minimax')button.classList.add('fish-hd-voice');
    button.setAttribute('aria-label',button.title);
    button.setAttribute('aria-pressed','false');
    button.onclick=()=>playVoice(text,button,false,provider);
    return button;
  }
  function voiceControls(text){
    const controls=document.createElement('span');
    controls.className='fish-voice-controls';
    controls.append(voiceButton(text,'default'),voiceButton(text,'minimax'));
    return controls;
  }
  const expandedTranscripts=new Set();
  function voiceCard(text,replyId,duration){
    const card=document.createElement('span');
    card.className='fish-voice-card';
    const play=document.createElement('button');
    play.type='button';
    play.className='fish-recording-play';
    play.dataset.voiceLabel='🔊';
    play.setAttribute('aria-label','播放语音，'+duration+'秒');
    const icon=document.createElement('span');
    icon.className='fish-voice-icon';
    icon.textContent=play.dataset.voiceLabel;
    play.append(icon,document.createTextNode(duration+' 秒'));
    setVoiceButton(play,'');
    play.onclick=()=>playVoice(null,play,false,'default',replyId,true);
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='fish-transcript-toggle';
    const transcript=document.createElement('span');
    transcript.className='fish-voice-transcript';
    transcript.textContent=text;
    const show=open=>{
      transcript.hidden=!open;
      toggle.textContent=open?'收起文字':'转文字';
      toggle.setAttribute('aria-expanded',String(open));
    };
    show(expandedTranscripts.has(replyId));
    toggle.onclick=()=>{
      const open=transcript.hidden;
      if(open)expandedTranscripts.add(replyId);else expandedTranscripts.delete(replyId);
      show(open);
    };
    card.append(play,toggle,voiceButton(text,'minimax'),transcript);
    return card;
  }
  const intervals=[
    ['fishActionCd','fish.actionRepeatCd','同动作间隔',0],
    ['fishIdleCd','fish.idleCd','闲聊间隔',90],
    ['fishScreenCd','fish.screenCd','看桌面间隔',300],
  ];
  const switches=[
    ['fishActions','fish.actions',true],['fishIdle','fish.idle',false],['fishAutoScreen','fish.autoScreen',false],
  ];
  for(const [id,key,fallback] of switches)$(id).checked=getPref(key,fallback);
  const actionCooldown=()=>Math.max(0,$('fishActionCd').valueAsNumber||0)*1000;
  const idleCooldown=()=>$('fishIdleCd').valueAsNumber>0?$('fishIdleCd').valueAsNumber*1000:90000;
  const screenCooldown=()=>Math.max(60,Math.min(7200,$('fishScreenCd').valueAsNumber||300))*1000;
  $('fishActions').onchange=()=>savePref('fish.actions',$('fishActions').checked);
  $('fishIdle').onchange=()=>{ savePref('fish.idle',$('fishIdle').checked); nextIdle=Date.now()+idleCooldown(); };
  $('fishAutoScreen').onchange=()=>{savePref('fish.autoScreen',$('fishAutoScreen').checked);nextScreen=Date.now()+screenCooldown();};
  const validInterval=(field,value)=>Number.isInteger(value)&&value>=Number(field.min)&&value<=Number(field.max);
  for(const [id,key,label,fallback] of intervals){
    const field=$(id);
    const stored=readStoredSetting(key);
    field.value=stored!==null&&validInterval(field,Number(stored))?Number(stored):fallback;
    field.onchange=()=>{
      if(!validInterval(field,field.valueAsNumber)){
        field.value=field.defaultValue;
        return;
      }
      field.defaultValue=field.value;
      savePref(key,field.valueAsNumber);
      if(id==='fishIdleCd')nextIdle=Date.now()+idleCooldown();
      if(id==='fishScreenCd')nextScreen=Date.now()+screenCooldown();
    };
    field.defaultValue=field.value;
    field.setAttribute('aria-label',label+'（秒）');
    for(const [direction,sign] of [[-1,'−'],[1,'+']]){
      const button=document.createElement('button');
      button.type='button';
      button.textContent=sign;
      button.setAttribute('aria-label',(direction<0?'减少':'增加')+label);
      button.onclick=()=>{
        if(direction<0)field.stepDown();else field.stepUp();
        field.dispatchEvent(new Event('change'));
      };
      if(direction<0)field.before(button);else field.after(button);
    }
  }
  const settingsOverlay=$('fishSettingsOverlay');
  function showSettings(open){
    settingsOverlay.hidden=!open;
    const button=$('fishSettingsButton');
    button.setAttribute('aria-expanded',String(open));
    button.setAttribute('aria-label',open?'关闭聊天设置':'打开聊天设置');
    (open?$('fishSettingsClose'):button).focus({preventScroll:true});
    requestAnimationFrame(desktopRegions);
  }
  $('fishSettingsButton').onclick=()=>showSettings(settingsOverlay.hidden);
  $('fishSettingsClose').onclick=()=>showSettings(false);
  settingsOverlay.addEventListener('keydown',event=>{if(event.key==='Escape')showSettings(false);});
  $('fishToggle').onclick=()=>{const body=$('fishBody');if(!settingsOverlay.hidden)showSettings(false);body.hidden=!body.hidden;$('fishToggle').textContent=body.hidden?'+':'−';$('fishToggle').setAttribute('aria-label',body.hidden?'展开聊天':'收起聊天');requestAnimationFrame(desktopRegions);};
  let lastAuto=0, lastActivity=Date.now(), nextIdle=Date.now()+idleCooldown(),nextScreen=Date.now()+screenCooldown();
  if(query.get('test')!=='1'){
    const legacy={};
    const wallpaperPrefix='wallpaper.';
    const wallpaperKeys=Object.keys(window.__deepseek?.settings||{});
    if(pinned){
      try{
        const cached=JSON.parse(readStoredSetting('deepseek-room.standalone.settings.v1')||'null');
        for(const key of wallpaperKeys){
          if(cached&&Object.hasOwn(cached,key))legacy[wallpaperPrefix+key]=window.__deepseek.settings[key];
        }
      }catch{}
      let pending={},timer;
      const flushWallpaperSettings=()=>{
        clearTimeout(timer);
        if(!Object.keys(pending).length)return;
        queueSettingsSave(pending);
        pending={};
      };
      window.addEventListener('fish-wallpaper-settings',event=>{
        for(const [key,value] of Object.entries(event.detail)){
          const name=wallpaperPrefix+key;
          editedSettings.add(name);
          pending[name]=value;
        }
        clearTimeout(timer);
        timer=setTimeout(flushWallpaperSettings,200);
      });
      window.addEventListener('pagehide',flushWallpaperSettings);
      document.addEventListener('visibilitychange',()=>{if(document.hidden)flushWallpaperSettings();});
    }
    const booleanFields=[...switches,['fishVoice','fish.voice'],['fishOwnVoice','fish.ownVoice']];
    for(const [,key] of booleanFields){
      const value=readStoredSetting(key);
      if(value==='0'||value==='1')legacy[key]=value==='1';
    }
    for(const [id,key] of intervals){
      const value=readStoredSetting(key);
      if(value!==null&&validInterval($(id),Number(value)))legacy[key]=Number(value);
    }
    const migrate=!demo&&Object.keys(legacy).length>0;
    settingsQueue=requestChatSettings(migrate?legacy:null,migrate).then(settings=>{
      if(pinned){
        const wallpaperSettings={};
        for(const key of wallpaperKeys){
          const name=wallpaperPrefix+key;
          if(Object.hasOwn(settings,name)&&!editedSettings.has(name))wallpaperSettings[key]=settings[name];
        }
        if(Object.keys(wallpaperSettings).length)window.__deepseek?.applySavedSettings(wallpaperSettings);
      }
      for(const [id,key] of booleanFields){
        if(typeof settings[key]!=='boolean'||editedSettings.has(key))continue;
        if(id==='fishOwnVoice'){ownVoiceEnabled=settings[key];renderOwnVoice();}
        else $(id).checked=settings[key];
      }
      for(const [id,key] of intervals){
        const field=$(id);
        if(!editedSettings.has(key)&&validInterval(field,settings[key]))field.defaultValue=field.value=settings[key];
      }
      nextIdle=Date.now()+idleCooldown();
      nextScreen=Date.now()+screenCooldown();
    }).catch(error=>{$('fishSettingsSaveStatus').textContent=error.message;});
  }
  // —— 气泡：支持流式渐进显示 ——
  const bubble=document.createElement('div');bubble.id='fishReplyBubble';bubble.className='chatter-bubble';bubble.hidden=true;
  bubble.innerHTML='<div class="chatter-heading"><span>♡</span><small>大肥鱼说</small><button type="button" class="chatter-close" aria-label="关闭回复">×</button></div><p class="fish-bubble-text"></p>';
  document.getElementById('layoutStage').appendChild(bubble);let bubbleTimer=null;
  const roomEl=()=>document.getElementById('room');
  const bubbleClose=bubble.querySelector('button');
  bubbleClose.onclick=()=>{bubble.hidden=true;roomEl().removeAttribute('data-ai-speaking');};
  let bubbleVoice=null, bubbleReplyId=null;
  const stripMarkers=text=>text.replace(/&&[^&\n]{1,40}&&/g,'').replace(/&&[^&\n]{0,40}$/,'').replace(/[\[【](?:语(?:音[\]】]?)?)?$/,'');
  function bubbleShow(){bubble.hidden=false;roomEl().setAttribute('data-ai-speaking','true');clearTimeout(bubbleTimer);}
  function bubblePartial(text){if(bubble.hidden||!bubble.dataset.streaming)bubble.dataset.streaming='1';bubbleVoice?.remove();bubbleVoice=bubbleReplyId=null;bubbleShow();bubble.querySelector('p').textContent=normalizeReply(stripMarkers(text)).trim();}
  function bubbleFinal(text,replyId){delete bubble.dataset.streaming;bubbleShow();bubble.querySelector('p').textContent=text;bubbleVoice?.remove();bubbleVoice=voiceControls(text);bubbleReplyId=replyId;bubbleClose.before(bubbleVoice);bubbleTimer=setTimeout(()=>{bubble.hidden=true;roomEl().removeAttribute('data-ai-speaking');},Math.min(60000,Math.max(15000,text.length*220)));}
  async function markSpoken(replyId,text,duration){
    if(!replyId||!duration)return;
    try{
      const r=await fetch('/history/voice',{method:'POST',headers:{
        'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN
      },body:JSON.stringify({reply_id:replyId,duration}),signal:AbortSignal.timeout(5000)});
      if(!r.ok)return;
      if(bubbleReplyId===replyId&&bubbleVoice){
        bubbleVoice.remove();
        bubbleVoice=voiceCard(text,replyId,duration);
        bubble.querySelector('p').replaceChildren(bubbleVoice);
        if(voiceJob?.recordingId===replyId){
          voiceJob.button=bubbleVoice.querySelector('.fish-recording-play');
          setVoiceButton(voiceJob.button,'playing');
        }
      }
      refresh();
    }catch{}
  }
  function add(who,text,spoken,replyId,duration){
    if(who!=='我')text=normalizeReply(text);
    const line=document.createElement('p');
    line.className=who==='我'?'fish-user':'fish-reply';
    const name=document.createElement('strong'), content=document.createTextNode(text), controls=voiceControls(text);
    name.textContent=who+'：';
    if(replyId&&duration)line.append(name,voiceCard(text,replyId,duration));
    else if(spoken){
      controls.classList.add('fish-voice-prefix');
      line.append(name,controls,content);
    }else line.append(name,content,controls);
    history.appendChild(line);
  }
  // —— 请求队列：用户消息优先，动作/闲聊排队而不是丢弃 ——
  const queue=[]; let processing=false, nativeTyping=false;
  let lastChatError='';
  function setStatusDefault(){ refresh(); }
  async function pump(){ if(processing)return; processing=true;
    try{ while(queue.length){ const {job}=queue.shift(); await job(); } }
    finally{ processing=false; $('fishSend').disabled=false; setStatusDefault(); }
  }
  function enqueue(job,user=false){
    const next={job,user};const firstAuto=user?queue.findIndex(item=>!item.user):-1;
    if(firstAuto<0)queue.push(next);else queue.splice(firstAuto,0,next);
    if(processing)status.textContent=user?'消息已排队，优先回复':'互动已排队（'+queue.length+'）';
    pump();
  }
  async function send(message, label, automatic=false, silentOk=false, image=null){
    if(!message)return;
    const canChooseVoice=()=>ownVoiceEnabled&&(!automatic||Date.now()-lastOwnVoice>=90000);
    const body={message,label:label||message,automatic,auto_voice:autoVoice.checked,
      allow_own_voice:canChooseVoice()};
    if(silentOk)body.silent_ok=true;
    if(image)body.image=image;
    lastChatError='';status.textContent=automatic?'正在回应互动…':'大肥鱼正在想…';
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),130000);
    try {
      const response=await fetch('/chat/stream',{method:'POST',headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},body:JSON.stringify(body),signal:controller.signal});
      if(!response.ok){ let detail='连接失败'; try{detail=(await response.json()).error||detail;}catch{} throw new Error(detail); }
      if(!response.body)throw new Error('浏览器不支持流式响应');
      const reader=response.body.getReader(), dec=new TextDecoder(); let buf='', partial='', final=null, silent=false, voice='', replyId=null;
      while(true){ const {done,value}=await reader.read(); if(done)break; buf+=dec.decode(value,{stream:true});
        let idx; while((idx=buf.indexOf('\n\n'))>=0){ const chunk=buf.slice(0,idx); buf=buf.slice(idx+2);
          const line=chunk.split('\n').find(l=>l.startsWith('data:')); if(!line)continue;
          let ev; try{ev=JSON.parse(line.slice(5).trim());}catch{continue;}
          if(ev.image_received)status.textContent='图片已送达大肥鱼，正在等回复…';
          if(ev.delta){partial+=ev.delta;bubblePartial(partial);}
          if(ev.silent)silent=true;
          if(ev.reply){final=normalizeReply(ev.reply);voice=ev.voice;replyId=ev.reply_id;bubbleFinal(final,replyId);}
          if(ev.error)throw new Error(ev.error);
        }
      }
      if(silent&&!final)return 'silent';
      if(final!==null){
        const chosen=voice==='chosen'&&canChooseVoice();
        if(chosen&&automatic)lastOwnVoice=Date.now();
        if(voice==='requested'||(voice==='automatic'&&autoVoice.checked)||chosen){
          const button=bubbleVoice?.querySelector('button');
          const recordingId=voice==='requested'||chosen?replyId:null;
          playVoice(final,button,true,'default',recordingId).then(played=>{
            if(played&&recordingId)markSpoken(recordingId,final,played.duration);
          });
        }
        return final;
      }
      throw new Error('连接中断，没有收到回复');
    } catch(e) {lastChatError='连接失败：'+(e.name==='AbortError'?'等待超时，请重新发送':e.message);status.textContent=lastChatError;return null;} finally {clearTimeout(timeout);}
  }
  let revision=-1, refreshing=false;
  async function refresh(){
    if(refreshing)return;
    refreshing=true;
    try{
      const r=await fetch('/history',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},signal:AbortSignal.timeout(5000)});
      if(!r.ok)throw new Error('读取记录失败');
      const d=await r.json();
      if(d.revision!==revision){
        const oldTop=history.scrollTop;
        const follow=revision<0||history.scrollHeight-history.clientHeight-oldTop<=12;
        history.replaceChildren();
        for(const item of d.messages)add(item.role,item.text,item.spoken,item.reply_id,item.duration);
        if(!d.messages.length)history.textContent='最近 24 小时还没有聊天记录。';
        history.scrollTop=follow?history.scrollHeight:oldTop;
        revision=d.revision;
      }
      if(!processing)status.textContent=(!d.ready?d.connection?.message:null)||lastChatError||(d.ready?(demo?'已连接 AstrBot · Alt+F4 退出':'已连接 AstrBot'):'正在重连 AstrBot');
    }catch(e){if(!processing)status.textContent='连接失败：'+e.message;}
    finally{refreshing=false;}
  }
  if(demo){
    root.querySelector('.fish-image-tools').hidden=true;
    for(const id of ['fishIdle','fishAutoScreen'])$(id).disabled=true;
  }
  setInterval(refresh,3000);refresh();
  const input=$('fishInput'); let composing=false;
  input.addEventListener('compositionstart',()=>composing=true);input.addEventListener('compositionend',()=>composing=false);
  let pendingImage=null;
  const imagePreview=$('fishImagePreview');
  async function imageData(file){
    if(!file.type.startsWith('image/'))throw new Error('请选择图片文件');
    if(file.size>20*1024*1024)throw new Error('图片不能超过 20 MB');
    const bitmap=await createImageBitmap(file);
    const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();
    return canvas.toDataURL('image/jpeg',.82).split(',')[1];
  }
  async function setImage(file){
    if(demo)return;
    try{pendingImage=await imageData(file);imagePreview.querySelector('img').src='data:image/jpeg;base64,'+pendingImage;imagePreview.hidden=false;status.textContent='图片已加入，点击发送给大肥鱼';}
    catch(e){status.textContent=e.message;}
  }
  $('fishAddImage').onclick=()=>$('fishImageFile').click();
  $('fishImageFile').onchange=e=>{if(e.target.files[0])setImage(e.target.files[0]);e.target.value='';};
  $('fishRemoveImage').onclick=()=>{pendingImage=null;imagePreview.hidden=true;imagePreview.querySelector('img').removeAttribute('src');};
  $('fishScreen').onclick=async()=>{try{status.textContent='正在截取并发送桌面…';const r=await fetch('/desktop/screenshot',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}});if(!r.ok)throw new Error('桌面截图失败');const image=await imageData(await r.blob());const text=input.value.trim();input.value='';$('fishRemoveImage').click();userSend(text||'请看看我现在的桌面画面。',image);}catch(e){status.textContent=e.message;}};
  root.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
  root.addEventListener('drop',e=>{const file=[...e.dataTransfer.files].find(f=>f.type.startsWith('image/'));if(file){e.preventDefault();setImage(file);}});
  function userSend(text,image=null){
    const now=Date.now();
    lastActivity=now; nextIdle=now+120000;
    enqueue(async()=>{ const reply=await send(text||'请看看这张图片。',image?'我发送了一张图片'+(text?'：'+text:''):'' ,false,false,image); if(reply&&reply!=='silent'){lastAuto=Date.now();} },true);
  }
  $('fishForm').onsubmit=e=>{e.preventDefault();const text=input.value.trim();if((!text&&!pendingImage)||composing)return;const image=pendingImage;input.value='';$('fishRemoveImage').click();userSend(text,image);};
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing&&e.keyCode!==229){e.preventDefault();$('fishForm').requestSubmit();}});
  const events={
    'touch.head.release':['摸摸头','（我轻轻摸了摸你的头）请自然地简短回应。'],
    'touch.cheek.release':['捏捏脸','（我轻轻捏了捏你的脸）请自然地简短回应。'],
    'emotion.cry':['捏脸惹哭了她','（我捏脸把你惹哭了）请结合你的心情简短回应。'],
    'emotion.comforted':['摸头安慰','（你哭了，我轻轻摸头安慰你，你想要抱抱）请自然地简短回应。'],
    'emotion.reassured':['摸头哄好了','（我摸了摸你的头，把你哄好了）请自然地简短回应。'],
    'emotion.hug.resume':['抱着摸摸头','（我抱着你，轻轻摸了摸你的头）请自然地简短回应。'],
    'study.reassured':['学习时摸摸头','（你学习累了，我摸摸你的头安慰你）请自然地简短回应。'],
    'emotion.hug':['抱抱','（我抱住你）请自然地简短回应。'],
    'meal.start':['喂大白饭','（我给你喂了一口大白饭）请自然地简短回应。'],
    'study.start':['一起学习','（我邀请你陪我学习）请自然地简短回应。'],
    'study.rest':['学习休息','（学习暂停了，我们休息一会儿）请自然地简短回应。'],
    'study.attention':['学习疲倦','（我们学习了一段时间，你有点累了）请自然地简短回应。']
  };
  const actionDeliveries=[], lastActionByReason=new Map();
  function recordAction(reason,result){actionDeliveries.push({reason,result,at:Date.now()});if(actionDeliveries.length>24)actionDeliveries.shift();}
  function handleFishAction(event){
    const reason=event.detail?.reason,e=events[reason];if(!e)return;
    const now=Date.now();lastActivity=now;nextIdle=now+120000;
    if(!$('fishActions').checked){recordAction(reason,'disabled');status.textContent='动作已识别，动作回应已关闭';return;}
    const previous=lastActionByReason.get(reason);
    if(previous!==undefined&&now-previous<actionCooldown()){recordAction(reason,'repeat_cooldown');status.textContent='同动作间隔中，其他互动仍可发送';return;}
    lastActionByReason.set(reason,now);recordAction(reason,'queued');
    enqueue(async()=>{recordAction(reason,'sending');const reply=await send(e[1],e[0],true);recordAction(reason,reply?'replied':'failed');if(reply&&reply!=='silent')lastAuto=Date.now();});
  }
  window.addEventListener('fish-action',handleFishAction);
  // —— 主动闲聊（加强版）：读取当前前台工作上下文，让模型决定开口还是保持安静 ——
  async function buildChatterMessage(){
    try{
      const r=await fetch('/cursor',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}});
      const d=await r.json();
      const fg=d.foreground||{};
      const wins=(d.windows||[]).filter(w=>w.title&&w.title!==fg.title).slice(0,6).map(w=>`${w.app}「${w.title}」`).join('；');
      return `（系统感知：用户现在前台是「${fg.app||'未知'}」，活动窗口「${fg.title||'无'}」；其他打开的窗口：${wins||'无'}）请以大肥鱼的口吻，结合用户正在做的事，主动说一句简短自然的闲聊或关心（30字以内）。如果此刻不适合打扰（比如正在专注工作、开会、看视频），就只回复四个字：[静默]`;
    }catch{
      return '（安静陪伴了一会儿）请以大肥鱼的口吻自然说一句简短的闲聊（30字以内），不要假装知道没有提供的信息。';
    }
  }
  async function idleTick(force){
    const now=Date.now();
    if(preview||!$('fishIdle').checked||processing||queue.length||nativeTyping||document.activeElement===input||document.hidden||window.__deepseek?.paused)return;
    if(!force&&(now<nextIdle||now-lastActivity<120000))return;
    nextIdle=now+idleCooldown();
    const message=await buildChatterMessage();
    if(processing||queue.length||nativeTyping||document.activeElement===input||lastActivity>now)return;
    enqueue(async()=>{ await send(message,'主动闲聊',true,true); });
  }
  setInterval(idleTick,5000);
  async function screenTick(){
    const now=Date.now();
    if(preview||!$('fishAutoScreen').checked||now<nextScreen||processing||queue.length||nativeTyping||document.activeElement===input||document.hidden||window.__deepseek?.paused||window.__fishFullscreenPaused)return;
    nextScreen=now+screenCooldown();
    enqueue(async()=>{
      try{
        const context=await fetch('/cursor',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}}).then(r=>r.json());
        const fg=context.foreground||{};
        const prompt=`（你现在有一次自主查看桌面的机会。当前前台程序：${fg.app||'未知'}；窗口：${fg.title||'无'}。如果想看用户正在做什么，只回复[看桌面]；如果不想看，只回复[静默]。不要猜测画面内容。）`;
        const decision=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},body:JSON.stringify({message:prompt,automatic:true,screen_decision:true})});
        if(!decision.ok||!(await decision.json()).look)return;
        if(!$('fishAutoScreen').checked||document.hidden||window.__fishFullscreenPaused)return;
        const response=await fetch('/desktop/screenshot/auto?interval='+Math.round(screenCooldown()/1000),{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}});
        if(!response.ok)throw new Error('主动截图失败');
        const image=await imageData(await response.blob());
        await send('（这是你刚刚自主查看的桌面画面。）你可以根据画面决定是否主动说一句简短自然的话；如果不适合打扰，只回复[静默]。','主动看桌面',true,true,image);
      }catch(e){status.textContent=e.message;}
    });
  }
  setInterval(screenTick,5000);
  // —— 全局鼠标位置（bridge 提供）：窗口失焦/固定到桌面后眼球也能继续跟随 ——
  let cursorPolling=false, desktopHover=null;
  function updateDesktopHover(pointer){
    const target=pointer?.over?document.elementFromPoint(pointer.x*innerWidth,pointer.y*innerHeight):null;
    const next=target?.closest('button:not(:disabled),.fish-resize-grip')??null;
    if(next===desktopHover)return;
    desktopHover?.classList.remove('fish-desktop-hover');
    desktopHover=next;
    desktopHover?.classList.add('fish-desktop-hover');
  }
  async function pollCursor(){
    if(cursorPolling||document.hidden)return; cursorPolling=true;
    try{
      const r=await fetch('/desktop/pointer',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}});
      if(!r.ok)throw new Error('Pointer unavailable');
      const pointer=await r.json();
      updateDesktopHover(pointer);
      if(pointer.x>=0&&window.__deepseek?.settings?.mouseTracking!==false){
        window.__fishCursor={nx:(pointer.x-.5)*2,ny:(pointer.y-.5)*2,t:Date.now()};
      }
    }catch{updateDesktopHover(null);}
    cursorPolling=false;
  }
  if(pinned)setInterval(pollCursor,65);
  // —— 供测试/调试 ——
  window.__fishChat={ send:text=>userSend(text), idle:force=>idleTick(!!force), state:()=>({processing,queued:queue.length,nextIdle}) };

  const memoryButton=document.createElement('button');memoryButton.id='fishMemory';memoryButton.type='button';memoryButton.textContent='✧ 记忆星图';
  document.getElementById('panelSettingsButton').after(memoryButton);
  if(demo){
    memoryButton.disabled=true;
    memoryButton.title='演示版不读取私人记忆';
  }
  memoryButton.onclick=async()=>{
    memoryButton.disabled=true;
    memoryButton.textContent='正在打开记忆星图…';
    try {
      const response=await fetch('/memory/open',{
        method:'POST',
        headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},
        body:'{}',signal:AbortSignal.timeout(5000),
      });
      if(!response.ok)throw new Error('无法打开记忆星图');
      memoryButton.textContent='✧ 记忆星图';
    } catch {
      memoryButton.textContent='打开失败 · 点击重试';
    } finally {
      memoryButton.disabled=false;
    }
  };

  const actionTrace=[];window.addEventListener('fish-action',e=>{actionTrace.push(e.detail.reason);if(actionTrace.length>12)actionTrace.shift();});
  function desktopRects(selector){
    const rects=[];
    for(const element of document.querySelectorAll(selector)){
      const style=getComputedStyle(element);
      if(element.hidden||style.visibility!=='visible'||style.display==='none')continue;
      const rect=element.getBoundingClientRect();
      let left=rect.left,top=rect.top,right=rect.right,bottom=rect.bottom;
      for(let parent=element.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent);
        if(style.overflowX==='visible'&&style.overflowY==='visible')continue;
        const clip=parent.getBoundingClientRect();
        if(style.overflowX!=='visible'){left=Math.max(left,clip.left);right=Math.min(right,clip.right);}
        if(style.overflowY!=='visible'){top=Math.max(top,clip.top);bottom=Math.min(bottom,clip.bottom);}
      }
      if(right>left&&bottom>top)rects.push({x:left,y:top,w:right-left,h:bottom-top});
    }
    return rects;
  }
  async function desktopRegions(){
    if(preview||document.hidden)return;
    const controls='.right-panel button:not(:disabled),#astrChat button:not(:disabled),#fishInput,.fish-chat-title,.fish-resize-grip,.fish-scroll-rail:not([aria-hidden=true]),#fishSettingsOverlay label,#settingsButton,#hugButton,#fishReplyBubble button,#settingsPanel';
    const regions=desktopRects(controls);
    const wheelRegions=desktopRects('#fishHistory,#fishSettingsOverlay,#settingsPanel,#fishReplyBubble .fish-bubble-text');
    regions.push(...(window.__deepseek?.desktopGestureRegions?.()||[]));
    const settingsOpen=!$('settingsOverlay').hidden, chatSettingsOpen=!settingsOverlay.hidden;
    const targets=['fishMemory','settingsButton','fishToggle','feedButton','studyButton','fishActions','character','hugButton','fishForm','fishInput','fishSend'].map(id=>{
      const {x,y,width,height}=$(id).getBoundingClientRect();
      return {id,x,y,w:width,h:height};
    });
    const companion={ready:!!window.__deepseek?.ready,paused:window.__deepseek?.paused,runtime:window.__deepseek?.runtime,fps:window.__deepseek?.fps,state:window.__deepseek?.state,drag:window.__deepseek?.drag,resources:window.__deepseek?.resources,actions:actionTrace,actionResponsesEnabled:$('fishActions').checked,actionRepeatSeconds:$('fishActionCd').valueAsNumber,actionDeliveries,pendingRequests:queue.length,processing};
    try{
      const response=await fetch('/desktop/regions',{
        method:'POST',headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},
        body:JSON.stringify({width:innerWidth,height:innerHeight,regions,wheelRegions,state:{settingsOpen,chatSettingsOpen,companion,targets}}),
      });
      const paused=!!(await response.json()).fullscreen;
      if(window.__fishFullscreenPaused!==paused){window.__fishFullscreenPaused=paused;window.dispatchEvent(new Event('fish-fullscreen'));}
    }catch{}
  }
  setInterval(desktopRegions,1000);desktopRegions();

  let nativePolling=false;
  setInterval(async()=>{
    if(preview||nativePolling||document.hidden)return;
    nativePolling=true;
    try{
      const r=await fetch('/desktop/commands',{headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN}});
      const d=await r.json();
      nativeTyping=!!d.typing;
      root.classList.toggle('fish-native-typing',nativeTyping);
      for(const text of d.commands||[])userSend(text);
    }catch{}finally{nativePolling=false;}
  },150);
})();
