# -*- coding: utf-8 -*-
"""记忆星图 v2：本地服务模式
- 星图：缩放(滚轮)/拖拽(空白处)/节点拖动/悬停翻转提示/点击暂停并打开详情
- 详情：查看全文、编辑当前来源记录、调整核心记忆等级、删除记忆或归档璃笺日记
- 侧边栏：实时状态 / 三级记忆库存 / 情绪分布 / 筛选 / 列表定位 / 刷新
用法: python 记忆星图.py  → 起 127.0.0.1:8765 并自动打开浏览器（关掉控制台即退出）
"""
import json, os, sys, io, glob, sqlite3, datetime
import hashlib, math, re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote



from data_paths import ASTRBOT_CORE
DATA = str(ASTRBOT_CORE / 'data')
CORE_MEM = os.path.join(DATA, 'plugin_data', 'astrbot_plugin_yuren_core', 'core_memory.json')
PORT = 8765


def load_core():
    try:
        items = json.load(open(CORE_MEM, encoding='utf-8'))
        return items if isinstance(items, list) else []
    except Exception:
        return []


def save_core(items):
    json.dump(items, open(CORE_MEM, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def split_living_memory(text, metadata):
    """Separate the plugin's fact suffix only when metadata confirms the match."""
    facts = metadata.get('key_facts')
    if not isinstance(facts, list):
        return None
    for limit in (5, len(facts)):
        visible_facts = [str(fact) for fact in facts[:limit] if fact]
        if not visible_facts:
            continue
        suffix = ' | ' + '；'.join(visible_facts)
        if text.endswith(suffix) and text[:-len(suffix)].strip():
            return {'summary': text[:-len(suffix)], 'facts': visible_facts}
    return None


def content_links(nodes):
    """Keep strong shared phrases and attach examples for the detail view."""
    texts = [' '.join(re.findall(r'[^\W_]+', n['text'].lower()))[:2400] for n in nodes]
    phrases = [
        {word[i:i + size] for word in text.split() for size in (3, 4)
         for i in range(len(word) - size + 1)}
        for text in texts
    ]
    index = defaultdict(list)
    for i, terms in enumerate(phrases):
        for term in sorted(terms):
            index[term].append(i)
    norms = [0.0] * len(nodes)
    shared = defaultdict(float)
    common_limit = max(2, math.ceil(len(nodes) * 0.55))
    for term, matches in index.items():
        weight = (1 + math.log((len(nodes) + 1) / (len(matches) + 1))) ** 2
        for i in matches:
            norms[i] += weight
        if len(term) == 4 and 1 < len(matches) <= common_limit:
            for pos, i in enumerate(matches):
                for j in matches[pos + 1:]:
                    shared[i, j] += weight

    candidates = sorted(
        ((weight / math.sqrt(norms[i] * norms[j]), i, j) for (i, j), weight in shared.items()),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    links, degree, seen = [], Counter(), set()
    for score, i, j in candidates:
        if score < 0.055:
            break
        a, b = nodes[i]['id'], nodes[j]['id']
        pair = tuple(sorted((a, b)))
        if a == b or pair in seen or degree[a] >= 3 or degree[b] >= 3:
            continue
        blocks = SequenceMatcher(None, texts[i], texts[j], autojunk=False).get_matching_blocks()
        evidence = []
        for block in sorted(blocks, key=lambda block: -block.size):
            phrase = texts[i][block.a:block.a + block.size].strip()
            for word in phrase.split():
                start = next((k for k in range(len(word) - 3)
                              if len(index[word[k:k + 4]]) <= common_limit), None)
                if start is not None:
                    evidence.append(word[max(0, start - 3):start + 11])
            if len(evidence) >= 2:
                break
        if not evidence:
            continue
        links.append([a, b, list(dict.fromkeys(evidence))[:2]])
        seen.add(pair)
        degree.update((a, b))
    return links


def memory_links(nodes):
    """Connect a few close matches per memory, with one line per pair."""
    by_id = {node['id']: node for node in nodes}
    reasons = defaultdict(dict)
    candidates = defaultdict(list)

    def register(kind, a, b, evidence):
        pair = tuple(sorted((a, b)))
        if a != b and kind not in reasons[pair]:
            reasons[pair][kind] = evidence
            candidates[kind].append(pair)

    for a, b, phrases in content_links(nodes):
        register('topic', a, b, phrases)

    ordered = sorted(by_id.values(), key=lambda node: (node['date'], node['id']))
    for kind, field in [('day', 'date'), ('emotion', 'emotion'), ('source', 'provenance')]:
        groups = defaultdict(list)
        for node in ordered:
            value = node[field]
            if kind == 'day':
                value = value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', value) else ''
            if value and value not in {'来源未记录', '来源未确认', 'QQ 私聊 · 身份待确认'}:
                groups[value].append(node['id'])
        for value, ids in groups.items():
            for a, b in zip(ids, ids[1:]):
                register(kind, a, b, [value])

    selected, degree = {}, Counter()
    for kind in ('topic', 'day', 'source', 'emotion'):
        type_degree = Counter()
        for a, b in candidates[kind]:
            pair = (a, b)
            if pair in selected or max(degree[a], degree[b]) >= 3:
                continue
            if kind != 'topic' and max(type_degree[a], type_degree[b]) >= 1:
                continue
            selected[pair] = kind
            degree.update(pair)
            type_degree.update(pair)
    return [[a, b, kind, reasons[a, b]] for (a, b), kind in selected.items()]


def scan_data():
    nodes, edges = [], []
    stats = {"core": 0, "sub": 0, "min": 0, "living": 0, "diary": 0}
    status = {"persona": "?", "model": "?", "max_turns": "?", "sleep": "清醒",
              "sleep_dot": "#a6e3a1", "version": "4.29.3"}
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        cfg=json.loads(open(os.path.join(DATA,'cmd_config.json'),encoding='utf-8-sig').read())
    except (OSError,ValueError):
        cfg={}
    accounts={str(x) for x in cfg.get('admins_id',[]) if str(x).isascii() and str(x).isdigit()}
    owner=next(iter(accounts)) if len(accounts)==1 else None
    qq_platforms={x['id'] for x in cfg.get('platform',[]) if x.get('type')=='aiocqhttp' and 'id' in x}

    def add_node(src, text, date, emotion="", level="", uid="", source_id=None, provenance=""):
        text = (text or "").strip()
        if not text:
            return None
        nid = uid or ("%s%d" % (src, len(nodes) + 1))
        node={"id": nid, "src": src, "text": text, "date": date or "", "emotion": emotion or "", "level": level,
              "provenance": provenance}
        if source_id is not None:
            node["source_id"]=source_id
            node["version"]=hashlib.sha256(text.encode()).hexdigest()
        nodes.append(node)
        return nid

    # 1) 核心记忆本（分级）
    for it in load_core():
        lvl = it.get("level", "core")
        stats[lvl] = stats.get(lvl, 0) + 1
        add_node("core", it.get("content", ""), it.get("ts", ""), it.get("emotion", ""), lvl,
                 uid="core|" + it.get("ts", "") + "|" + it.get("content", "")[:24],
                 provenance={'wallpaper':'壁纸 · 主人','qq':'QQ 私聊 · 主人'}.get(it.get('source'),'来源未记录'))

    # 2) 璃笺日记（新版保存到 SQLite，旧版 JSON 仍兼容）
    lj = os.path.join(DATA, 'plugin_data', 'astrbot_plugin_lijian')
    lj_db = os.path.join(lj, 'lijian.sqlite3')
    if os.path.exists(lj_db):
        try:
            con = sqlite3.connect('file:' + lj_db.replace('\\', '/') + '?mode=ro', uri=True)
            for note_id, title, body, day, created in con.execute(
                "select id, title, body_md, diary_date, created_at from notes "
                "where kind='diary' and archived=0 order by created_at desc limit 400"
            ):
                entry = (body or title or '').strip()
                if entry:
                    add_node('diary', entry, day or str(created or '')[:10],
                             uid='diary|'+note_id, source_id=note_id)
                    stats['diary'] += 1
            con.close()
        except Exception:
            pass
    for fp in glob.glob(os.path.join(lj, '**', '*.json'), recursive=True):
        try:
            arr = json.load(open(fp, encoding='utf-8-sig'))
            arr = arr if isinstance(arr, list) else [arr]
            for it in arr:
                t = it.get('content') or it.get('text') or '' if isinstance(it, dict) else str(it)
                if t and len(str(t)) > 20:
                    add_node("diary", str(t), it.get('date', '') if isinstance(it, dict) else '')
                    stats["diary"] += 1
        except Exception:
            continue

    # 3) livingmemory（自动探测）
    for db in glob.glob(os.path.join(DATA, 'plugin_data', 'astrbot_plugin_livingmemory', '**', '*.db'), recursive=True) + \
              glob.glob(os.path.join(DATA, 'knowledge_base', '*.db')):
        try:
            con = sqlite3.connect(db)
            if os.path.basename(db) == 'livingmemory.db':
                for memory_id, txt, created, meta in con.execute(
                    "select id, text, created_at, metadata from documents order by created_at desc limit 400"
                ):
                    if txt and len(str(txt).strip()) > 15:
                        canonical=os.path.join(DATA,'plugin_data','astrbot_plugin_livingmemory','livingmemory.db')
                        source_id=memory_id if os.path.normcase(os.path.abspath(db))==os.path.normcase(os.path.abspath(canonical)) else None
                        try:
                            info=json.loads(meta or '{}')
                        except (ValueError,TypeError):
                            info={}
                        if not isinstance(info, dict):
                            info={}
                        platform, _, tail=str(info.get('source_session_id') or info.get('session_id') or '').partition(':')
                        kind, _, peer=tail.partition(':')
                        if platform=='webchat' and kind=='FriendMessage' and peer.startswith('webchat!wallpaper_companion!'):
                            provenance='壁纸 · 主人'
                        elif platform in qq_platforms and kind=='FriendMessage':
                            provenance='QQ 私聊 · 主人' if owner and peer==owner else 'QQ 私聊 · 其他联系人' if owner else 'QQ 私聊 · 身份待确认'
                        elif platform in qq_platforms and kind=='GroupMessage':
                            provenance='QQ 群聊'
                        else:
                            provenance='来源未确认'
                        emotion={'positive':'正向','neutral':'平静','negative':'负向','mixed':'复杂'}.get(info.get('sentiment'),'')
                        text=str(txt).strip()
                        add_node('living', text, str(created or '')[:19],emotion,
                                 uid=f'living|{memory_id}' if source_id is not None else '', source_id=source_id,
                                 provenance=provenance)
                        if parts := split_living_memory(text, info):
                            nodes[-1].update(parts)
                        stats['living'] += 1
                con.close()
                continue
            for (t,) in con.execute("select name from sqlite_master where type='table'"):
                if 'memor' not in t.lower() or '_fts' in t.lower():
                    continue
                cols = [c[1] for c in con.execute('pragma table_info(%s)' % t)]
                tc = next((c for c in ('content', 'text', 'memory', 'summary', 'fact') if c in cols), None)
                if not tc:
                    continue
                ts_col = next((c for c in ('created_at', 'ts', 'time', 'updated_at') if c in cols), None)
                for row in con.execute("select %s%s from %s order by rowid desc limit 400" % (tc, (',' + ts_col) if ts_col else '', t)):
                    txt = str(row[0]).strip()
                    if len(txt) > 15:
                        add_node("living", txt[:280], str(row[1])[:19] if ts_col and len(row) > 1 else "")
                        stats["living"] += 1
            con.close()
        except Exception:
            continue

    edges = memory_links(nodes)

    # 5) 状态
    try:
        ar = cfg['agent_runner']['config']
        status['persona'] = ar['persona']['persona_id']
        status['model'] = ar['model']['provider_id']
        status['max_turns'] = ar['compression']['max_turns']
    except Exception:
        pass
    try:
        st = json.load(open(os.path.join(DATA, 'plugin_data', 'astrbot_plugin_yuren_night', 'state.json'), encoding='utf-8'))
        if st.get('sleeping'):
            status['sleep'] = '💤 睡眠中（%s 入睡）' % st.get('bedtime', '?')
            status['sleep_dot'] = '#89b4fa'
    except Exception:
        pass

    emo = {}
    for n in nodes:
        e = n['emotion'] or '未标注'
        emo[e] = emo.get(e, 0) + 1

    return {"generated_at": generated_at, "status": status, "stats": stats,
            "emotions": emo, "nodes": nodes, "edges": edges}


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>大肥鱼 · 记忆星图</title>
<style>
* { box-sizing:border-box; }
:root { color-scheme:dark; font:12px/1.5 "Microsoft YaHei",system-ui,sans-serif; background:#101114; color:#d9dce2; }
body { margin:0; height:100vh; display:grid; grid-template-rows:25px 39px minmax(0,1fr); overflow:hidden; }
button,input,select,textarea { font:inherit; }
button { cursor:pointer; }
button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible { outline:1px solid #9bbfe1; outline-offset:2px; }
[hidden] { display:none!important; }
#title-strip { display:flex; align-items:center; justify-content:space-between; padding:0 12px; background:#8162c8; color:#f6f0ff; font-size:11px; }
#toolbar { background:#1d2229; border-bottom:1px solid #303640; display:flex; align-items:center; gap:10px; padding:0 11px; }
#toolbar strong { font-size:13px; white-space:nowrap; }
#toolbar strong span { color:#9bbce1; }
#s-gen { color:#89929d; font-size:10px; white-space:nowrap; }
.toolbar-controls { display:flex; align-items:center; gap:6px; margin-left:auto; min-width:0; }
#star-search { width:clamp(90px,15vw,220px); min-width:0; background:#252c36; color:#e8eaf0; border:1px solid #353d48; border-radius:4px; padding:3px 7px; }
.btn { border:1px solid #373e48; border-radius:4px; background:#252b33; color:#d5dae2; padding:3px 8px; white-space:nowrap; }
.btn:hover { background:#313a46; }
.btn[aria-pressed=true], .btn.primary { background:#2b4c6b; color:#cce5ff; border-color:#3f6383; }
.btn.danger { color:#ff9aab; }
.btn:disabled { opacity:.55; cursor:wait; }
#workspace { min-height:0; display:grid; grid-template-columns:clamp(158px,11.75vw,226px) minmax(0,1fr) minmax(300px,42%); }
#workspace.dashboard-hidden { grid-template-columns:clamp(158px,11.75vw,226px) minmax(0,1fr); }
#side,#dashboard { min-width:0; overflow:auto; scrollbar-color:#40434a transparent; scrollbar-width:thin; }
#side { background:#22262d; padding:8px 10px; border-right:1px solid #353a42; }
#side section { padding:8px 0; border-bottom:1px solid #353a42; }
h2 { margin:0 0 6px; font-size:11px; font-weight:600; color:#a6aeb9; }
.row { display:flex; justify-content:space-between; gap:6px; padding:3px 0; font-size:11px; }
.row span { color:#aab1bc; }
.row b { text-align:right; overflow-wrap:anywhere; color:#e0e3e8; }
.num { font-variant-numeric:tabular-nums; color:#9ca6b4; }
.dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:6px; }
#side .sub { color:#a2abb7; font-size:10px; margin:7px 0 0; }
#chips { display:flex; gap:3px; flex-wrap:wrap; }
.chip { border:0; border-radius:3px; color:#aeb8c4; background:#303641; padding:2px 6px; cursor:pointer; }
.chip.on { color:#d7ebff; background:#2f516f; }
#legend label,#view-options label { display:flex; align-items:center; gap:5px; margin:4px 0; cursor:pointer; color:#b7bec8; }
#view-options label:last-child { white-space:nowrap; }
input[type=checkbox] { accent-color:#719bc6; margin:0; }
#stage { position:relative; min-width:0; overflow:hidden; background:radial-gradient(ellipse at 56% 48%,#161921,#111217 73%); }
canvas { display:block; width:100%; height:100%; }
#stage-status { position:absolute; right:10px; bottom:8px; color:#858e9e; font:10px/1.5 system-ui,sans-serif; pointer-events:none; }
#tip,#detail { position:absolute; border:1px solid #363d48; background:#232830f5; color:#d3d9e0; border-radius:8px; box-shadow:0 10px 30px #0007; }
#tip { pointer-events:none; max-width:min(260px,calc(100% - 16px)); padding:8px 10px; display:none; font-size:11px; z-index:9; }
#tip .d { color:#a1a9b6; }
#detail { display:none; width:min(365px,calc(100% - 16px)); max-height:calc(100% - 16px); overflow:auto; padding:11px; z-index:20; }
#detail .hd { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; }
#detail .hd b { color:#e4e8ee; }
#detail .meta { margin:5px 0; color:#aeb9c7; font-size:11px; }
#d-links { white-space:pre-line; overflow-wrap:anywhere; }
#d-text,#d-level { width:100%; color:#dce1e8; background:#1a1e25; border:1px solid #3a424d; border-radius:4px; padding:6px; }
#d-text { min-height:135px; resize:vertical; }
#d-level { width:auto; }
#detail .ops { display:flex; flex-wrap:wrap; gap:5px; }
#facts-dialog { margin:auto; width:min(500px,calc(100% - 32px)); max-height:75vh; background:#20252c; color:#dce1e8; border:1px solid #3a424d; border-radius:8px; padding:16px; }
#facts-dialog::backdrop { background:#090b10aa; }
#facts-dialog header { display:flex; justify-content:space-between; align-items:center; }
#facts-dialog ol { padding-left:22px; overflow-wrap:anywhere; }
#facts-dialog li+li { margin-top:6px; }
#dashboard { border-left:1px solid #383443; background:#101011; padding:11px 12px; }
#dashboard h2 { color:#a6a7ad; margin:9px 0 6px; }
.charts { display:grid; grid-template-columns:1.35fr 1fr; gap:8px; }
.chart,.panel { min-width:0; background:#171719; border:1px solid #252527; border-radius:6px; overflow:hidden; }
.chart { padding:8px; }
.chart small { color:#a6a8b1; }
.chart svg { width:100%; height:65px; display:block; margin:5px 0; }
.chart-note { font-size:10px; color:#a1a4ae; }
#dashboard .row { padding:6px 9px; border-bottom:1px solid #202023; }
#dashboard .row:last-child { border-bottom:0; }
#mlist { max-height:38vh; overflow:auto; scrollbar-width:thin; }
.mi { display:grid; grid-template-columns:70px minmax(0,1fr) auto; align-items:center; gap:8px; width:100%; padding:7px 8px; border:0; border-bottom:1px solid #222225; background:transparent; text-align:left; color:#dfe1e5; }
.mi:hover,.mi.on { background:#282e38; }
.mi .entry { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mi .d,.mi .e { font-size:10px; color:#a2a6b0; white-space:nowrap; }
#scan-status { color:#9dabbd; font-size:10px; }
@media(max-width:980px) { #workspace { grid-template-columns:155px minmax(0,1fr) minmax(265px,38%); } #s-gen { display:none; } }
@media(max-width:750px) { #workspace { grid-template-columns:135px minmax(0,1fr); } #workspace.dashboard-hidden { grid-template-columns:135px minmax(0,1fr); } #dashboard { position:absolute; right:0; top:64px; bottom:0; width:min(420px,72vw); z-index:21; } #toolbar { gap:4px; } }
@media(max-width:520px) { #toolbar strong { display:none; } .toolbar-controls { margin:0 auto; gap:4px; } #toolbar .btn { padding-inline:5px; } }
</style></head>
<body>
<div id="title-strip"><span>大肥鱼 · 工作台 · 记忆导航</span><span>本地记忆</span></div>
<header id="toolbar">
  <strong>大肥鱼 <span>·</span> 记忆航图</strong><span id="s-gen"></span>
  <div class="toolbar-controls">
    <button type="button" class="btn" id="view-space" aria-pressed="true">球壳</button>
    <button type="button" class="btn" id="view-flat" aria-pressed="false">平面</button>
    <button type="button" class="btn" id="reset-view" title="复位视角">复位</button>
    <input id="star-search" type="search" placeholder="搜索记忆 / 来源" aria-label="搜索记忆">
    <button type="button" class="btn" id="toggle-labels" aria-pressed="true">标签</button>
    <button type="button" class="btn" id="toggle-dashboard" aria-pressed="true">数据</button>
  </div>
</header>
<main id="workspace">
<aside id="side" aria-label="航图控制">
  <section><h2>记忆来源</h2><div id="chips"></div></section>
  <section><h2>分层</h2>
    <div class="row"><span><i class="dot" style="background:#dfc183"></i>核心</span><span class="num" id="c-core">0</span></div>
    <div class="row"><span><i class="dot" style="background:#91b2db"></i>潜意识</span><span class="num" id="c-sub">0</span></div>
    <div class="row"><span><i class="dot" style="background:#8290a6"></i>小事</span><span class="num" id="c-min">0</span></div>
    <div class="row"><span><i class="dot" style="background:#8bc2ba"></i>情节记忆</span><span class="num" id="c-living">0</span></div>
    <div class="row"><span><i class="dot" style="background:#c9a2d2"></i>璃笺日记</span><span class="num" id="c-diary">0</span></div>
  </section>
  <section><h2>情绪分布</h2><div id="emo"></div></section>
  <section><h2>航线类型</h2><div id="legend"></div></section>
  <section id="view-options"><h2>显示</h2>
    <label><input type="checkbox" id="auto-orbit"> 缓慢自转</label>
    <label><input type="checkbox" id="show-all-routes"> 显示全部航线</label>
    <label><input type="checkbox" id="emotion-tint" checked> 星点按情绪着色</label>
    <label>星点大小 <input id="star-size" type="range" min="0.6" max="1.6" step="0.1" value="1" style="min-width:0;width:100%"></label>
  </section>
  <section><h2>操作</h2><p class="sub" id="hint">滚轮缩放 · 拖空白处平移<br>按住 Shift 拖动旋转 · 点击星点查看详情</p></section>
  <section><button type="button" class="btn" id="btn-refresh">↻ 重新扫描</button> <span id="scan-status" role="status"></span></section>
</aside>
<div id="stage">
  <canvas id="cv"></canvas>
  <div id="stage-status"></div>
  <div id="tip"></div>
  <div id="detail">
    <div class="hd"><b id="d-title">记忆详情</b><button class="btn" id="d-close" type="button" aria-label="关闭详情">×</button></div>
    <div class="meta" id="d-meta"></div>
    <div class="meta" id="d-links"></div>
    <textarea id="d-text"></textarea>
    <div class="ops">
      <button type="button" class="btn" id="d-facts" hidden>查看记忆要点</button>
      <select id="d-level"><option value="core">⭐ 核心</option><option value="sub">🌙 潜意识</option><option value="min">📄 小事</option></select>
      <span class="btn primary" id="d-save">保存</span>
      <span class="btn" id="d-archive">归档</span>
      <span class="btn danger" id="d-del">删除</span>
    </div>
    <div id="d-msg" style="font-size:11px;color:#a6e3a1;margin-top:8px;display:none"></div>
  </div>
  <dialog id="facts-dialog" aria-labelledby="facts-title">
    <header><strong id="facts-title">记忆要点</strong><form method="dialog"><button class="btn" aria-label="关闭记忆要点">关闭</button></form></header>
    <ol id="facts-list"></ol>
  </dialog>
</div>
<aside id="dashboard" aria-label="记忆数据">
  <div class="charts">
    <section class="chart"><small>最近七天 · 记忆记录</small><svg id="activity-chart" viewBox="0 0 180 65" preserveAspectRatio="none" role="img" aria-label="最近七天记忆数量曲线"></svg><div class="chart-note" id="activity-note"></div></section>
    <section class="chart"><small>按来源分布</small><svg id="source-chart" viewBox="0 0 120 65" preserveAspectRatio="none" role="img" aria-label="各来源记忆数量柱状图"></svg><div class="chart-note" id="source-note"></div></section>
  </div>
  <h2>最近记忆 · 点击定位</h2><div class="panel" id="mlist"></div>
  <h2>运行状态</h2>
  <div class="panel">
    <div class="row"><span>当前人格</span><b id="s-persona"></b></div>
    <div class="row"><span>大脑模型</span><b id="s-model"></b></div>
    <div class="row"><span>上下文轮数</span><b id="s-turns"></b></div>
    <div class="row"><span>作息状态</span><b id="s-sleep"></b></div>
  </div>
</aside>
</main>
<script src="/app/bridge-token.js"></script><script>
const esc=v=>String(v??'').replace(/[&<>"\']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let DATA = null;
const EMO_COLOR = {
  '正向':'#8ee2ac','平静':'#7dbdff','负向':'#f47f76','复杂':'#c591ff',
  '开心':'#f9d471','感动':'#f4a9d5','争吵':'#e95c99','重要决定':'#70dedc',
  '心疼':'#f5b48d','未标注':'#8b93a8',
};
let emotionColors=new Map(Object.entries(EMO_COLOR));
const emotionOf=node=>node.emotion||'未标注';
const emotionColor=label=>emotionColors.get(label)||EMO_COLOR['未标注'];
const memorySummary=node=>node.summary??node.text;
const SRC_R = {"core":6.5, "living":4.2, "diary":5.2};
const LV_NAME = {"core":"核心","sub":"潜意识","min":"小事"};
const RELATIONS = {
  topic:{label:'内容相近',color:'#9fb9ff'},
  day:{label:'同一天',color:'#eac18a'},
  emotion:{label:'相同情绪',color:'#e8a9dc'},
  source:{label:'相同来源',color:'#85d6c4'},
};
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const $ = id => document.getElementById(id);
let W=0, H=0, pixelScale=1, zoom=1, targetZoom=1, panX=0, panY=0, lastFrame=null;
let nodes=[], edges=[], byId={};
let filterSrc=null, selected=null, hovered=null, dragging=null, panning=null;
let search='', visibleNodes=[], visibleEdges=[];
const disabledRoutes=new Set();
let frameId=null, idleTimer=null, scanning=false;
let dragTarget=null, motionTime=null;
let dustPath, hoverPoint=null;
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const DUST = Array.from({length:132},()=>({
  x:Math.random(), y:Math.random(), s:0.55+Math.random()*1.25
}));

function resize(){
  const width=cv.clientWidth, height=cv.clientHeight;
  pixelScale=Math.min(window.devicePixelRatio||1,1,Math.sqrt(800000/Math.max(1,width*height)));
  const nextW=Math.max(1,Math.round(width*pixelScale));
  const nextH=Math.max(1,Math.round(height*pixelScale));
  if(nextW===W&&nextH===H)return;
  if(W&&H){ panX*=nextW/W; panY*=nextH/H; }
  W=cv.width=nextW; H=cv.height=nextH;
  dustPath=new Path2D();
  for(const {x,y,s} of DUST){
    const r=s*pixelScale;
    dustPath.moveTo(x*W+r,y*H);
    dustPath.arc(x*W,y*H,r,0,Math.PI*2);
  }
  requestDraw();
}
new ResizeObserver(resize).observe(cv);
const s2x = wx => wx*W*zoom + panX;  const s2y = wy => wy*H*zoom + panY;
const nodeX=n=>n.x+n.ox+n.fx;
const nodeY=n=>n.y+n.oy+n.fy;
let yaw=0.28, pitch=0.31, flat=false, labels=true, orbit=!reducedMotion.matches, orbitTime=null;
const orbitButton=$('auto-orbit');
function renderOrbit(){
  orbitButton.checked=orbit;
  orbitButton.disabled=flat;
}
orbitButton.onchange=()=>{orbit=orbitButton.checked;orbitTime=null;requestDraw();};
renderOrbit();
function camera(){
  const angle=flat?0:yaw, tilt=flat?0:pitch;
  return {c:Math.cos(angle),s:Math.sin(angle),cp:Math.cos(tilt),sp:Math.sin(tilt)};
}
function project(n,view=camera()){
  const x=nodeX(n)-0.5,y=nodeY(n)-0.48,z=flat?0:n.z;
  const {c,s,cp,sp}=view,depth=s*x+c*z;
  const scale=Math.min(W,H)*zoom*1.26;
  const viewDepth=y*sp+depth*cp;
  const perspective=1/Math.max(0.55,1-viewDepth*0.48);
  return {x:s2x(0.5)+(x*c-z*s)*scale*perspective,
          y:s2y(0.48)+(y*cp-depth*sp)*scale*perspective,depth:viewDepth,perspective};
}
function dragCoordinates(x,y,view){
  const scale=Math.min(W,H)*zoom*1.26*view.perspective;
  const horizontal=(x-s2x(0.5))/scale,vertical=(y-s2y(0.48))/scale;
  const {c,s,cp,sp}=camera(),depth=view.depth*cp-vertical*sp;
  return {x:0.5+horizontal*c+depth*s,
          y:0.48+vertical*cp+view.depth*sp,
          z:depth*c-horizontal*s};
}
function pickStar(x,y){
  let hit=null,best=Infinity;
  const size=Number($('star-size').value);
  const view=camera();
  for(const n of visibleNodes){
    const p=project(n,view),distance=Math.hypot(x-p.x,y-p.y);
    if(distance<Math.max(10,n.r*2.5*size*p.perspective)*pixelScale&&distance<best){hit=n;best=distance;}
  }
  return hit;
}

function layoutStars(){
  const radius=Math.ceil(Math.sqrt(nodes.length));
  const slots=[];
  for(let row=-radius;row<=radius;row++){
    for(let column=-radius;column<=radius;column++){
      const x=column+(Math.abs(row)%2)*0.5, y=row*Math.sqrt(3)/2;
      slots.push({x,y,distance:x*x+y*y});
    }
  }
  slots.sort((a,b)=>a.distance-b.distance);
  const positions=slots.slice(0,nodes.length);
  const spread=Math.max(1,...positions.map(p=>Math.max(Math.abs(p.x),Math.abs(p.y))));
  const neighbors=new Map(nodes.map(n=>[n,[]]));
  for(const {a,b} of edges){neighbors.get(a).push(b);neighbors.get(b).push(a);}
  const ranked=[...nodes].sort((a,b)=>neighbors.get(b).length-neighbors.get(a).length||a.id.localeCompare(b.id));
  const ordered=new Set();
  for(const start of ranked){
    if(ordered.has(start))continue;
    const group=new Set([start]);
    for(const node of group){
      for(const neighbor of neighbors.get(node))if(!ordered.has(neighbor))group.add(neighbor);
      ordered.add(node);
    }
  }
  const available=[...positions];
  const placed=new Map();
  const scale=Math.min(0.32/spread,0.19);
  for(const node of ordered){
    const anchors=neighbors.get(node).map(n=>placed.get(n)).filter(Boolean);
    let best=0,bestCost=Infinity;
    for(let i=0;i<available.length;i++){
      const p=available[i];
      const cost=p.distance*0.16+anchors.reduce((sum,a)=>sum+(a.x-p.x)**2+(a.y-p.y)**2,0);
      if(cost<bestCost){best=i;bestCost=cost;}
    }
    const [p]=available.splice(best,1);
    placed.set(node,p);
    node.x=0.5+p.x*scale;
    node.y=0.48+p.y*scale;
    const shell=Math.sqrt(Math.max(0.024,0.32**2-((p.x*scale)**2+(p.y*scale)**2)*0.65));
    node.z=(placed.size%2===0?1:-1)*shell*(0.57+0.38*Math.abs(Math.sin(p.x*2.33+p.y*3.76)));
  }
}

async function loadData(){
  if(scanning)return;
  scanning=true;
  const button=$('btn-refresh'), status=$('scan-status');
  button.disabled=true;
  status.textContent=' 正在扫描…';
  try {
    const r=await fetch('/memory/data',{
      headers:{'X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},
      signal:AbortSignal.timeout(15000)
    });
    if(!r.ok)throw new Error('扫描失败');
    DATA=await r.json();
    emotionColors=new Map(Object.entries(EMO_COLOR));
    let extra=0;
    for(const label of Object.keys(DATA.emotions).sort()){
      if(!emotionColors.has(label))emotionColors.set(label,`hsl(${(33+137.508*extra++)%360} 76% 67%)`);
    }
    nodes=DATA.nodes.map(n=>({...n,ox:0,oy:0,fx:0,fy:0,r:SRC_R[n.src]||4,ph:Math.random()*7,
      label:memorySummary(n).replace(/\s+/g,' ').trim().slice(0,9)}));
    byId=Object.fromEntries(nodes.map(n=>[n.id,n]));
    edges=DATA.edges.map(([a,b,kind,reasons])=>({a:byId[a],b:byId[b],kind,reasons})).filter(e=>e.a&&e.b);
    layoutStars();
    zoom=targetZoom=1;
    panX=panY=0;
    hovered=dragging=null;
    dragTarget=null;
    closeDetail();
    renderSidebar();
    status.textContent='';
  } catch {
    status.textContent=' 扫描失败，请重试';
  } finally {
    scanning=false;
    button.disabled=false;
  }
}

function renderSidebar(){
  const $ = id => document.getElementById(id);
  $('s-persona').textContent = DATA.status.persona;
  $('s-model').textContent = DATA.status.model;
  $('s-turns').textContent = DATA.status.max_turns;
  $('s-sleep').innerHTML = '<span class="dot" style="background:'+DATA.status.sleep_dot+'"></span>'+DATA.status.sleep;
  $('s-gen').textContent = '生成于 '+DATA.generated_at;
  $('c-core').textContent = DATA.stats.core||0;
  $('c-sub').textContent = DATA.stats.sub||0;
  $('c-min').textContent = DATA.stats.min||0;
  $('c-living').textContent = DATA.stats.living||0;
  $('c-diary').textContent = DATA.stats.diary||0;
  const emo = $('emo');
  emo.innerHTML = Object.entries(DATA.emotions).map(([k,v])=>{
    const c = emotionColor(k);
    return '<div class="row"><span><i class="dot" style="background:'+c+'"></i>'+esc(k)+'</span><b>'+v+'</b></div>';
  }).join('') || '<div style="color:#3d4567;font-size:11px">还没有情绪分布</div>';
  const chips = $('chips');
  chips.innerHTML = ['all','core','living','diary'].map(s=>{
    const names = {all:'全部', core:'核心', living:'情节', diary:'日记'};
    const on = (filterSrc===s)||(!filterSrc&&s==='all');
    return '<button type="button" class="chip'+(on?' on':'')+'" data-s="'+s+'" aria-pressed="'+on+'">'+names[s]+'</button>';
  }).join('');
  chips.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{ filterSrc = ch.dataset.s==='all'?null:ch.dataset.s; renderSidebar(); });
  $('legend').innerHTML = Object.entries(RELATIONS).map(([key,{label,color}])=>
    `<label><input type="checkbox" value="${key}" ${disabledRoutes.has(key)?'':'checked'}><i class="dot" style="background:${color}"></i>${label}</label>`).join('');
  $('legend').querySelectorAll('input').forEach(input=>input.onchange=()=>{
    if(input.checked)disabledRoutes.delete(input.value);else disabledRoutes.add(input.value);
    applyFilters();
  });
  renderCharts();
  applyFilters();
}

function applyFilters(){
  hovered=null;
  $('tip').style.display='none';
  visibleNodes=nodes.filter(n=>(!filterSrc||n.src===filterSrc)&&
    (!search||[memorySummary(n),n.provenance,n.emotion,n.date].some(value=>String(value??'').toLowerCase().includes(search))));
  const visible=new Set(visibleNodes);
  visibleEdges=edges.filter(e=>visible.has(e.a)&&visible.has(e.b)&&!disabledRoutes.has(e.kind));
  if(selected&&!visible.has(selected))closeDetail();
  const list=$('mlist');
  list.innerHTML=[...visibleNodes].sort((a,b)=>b.date.localeCompare(a.date)).map(n=>{
    const e = emotionOf(n);
    return '<button type="button" class="mi'+(selected===n?' on':'')+'" data-id="'+esc(n.id)+'"><span class="d">'+esc((n.date||'').slice(0,10))+'</span><span class="entry">'+esc(memorySummary(n))+'</span><span class="e" style="color:'+emotionColor(e)+'">'+esc(e)+'</span></button>';
  }).join('') || '<div class="row">没有符合条件的记忆</div>';
  list.querySelectorAll('.mi').forEach(el=>el.onclick=()=>{ selectNode(el.dataset.id, true); });
  $('stage-status').textContent=`${visibleNodes.length} 星点 · ${visibleEdges.length} 航线`;
  requestDraw();
}

function renderCharts(){
  const counts=new Map();
  const today=new Date();
  for(let i=6;i>=0;i--){
    const day=new Date(today);day.setDate(day.getDate()-i);
    counts.set([day.getFullYear(),day.getMonth()+1,day.getDate()].map(v=>String(v).padStart(2,'0')).join('-'),0);
  }
  for(const n of nodes){
    const date=n.date.slice(0,10);
    if(counts.has(date))counts.set(date,counts.get(date)+1);
  }
  const values=[...counts.values()], max=Math.max(1,...values);
  const line=values.map((count,i)=>`${i*30},${57-count/max*48}`).join(' ');
  $('activity-chart').innerHTML=`<path d="M0 57H180 M0 32H180 M0 8H180" stroke="#313134" fill="none"/><polygon points="0,57 ${line} 180,57" fill="#77787b35"/><polyline points="${line}" stroke="#e1e2e4" fill="none" stroke-width="1.3"/>`;
  $('activity-note').textContent=`近七天 ${values.reduce((a,b)=>a+b,0)} 条 · 今天 ${values.at(-1)} 条`;
  const sources=['core','living','diary'].map(source=>nodes.filter(n=>n.src===source).length);
  const peak=Math.max(1,...sources);
  $('source-chart').innerHTML='<path d="M0 57H120" stroke="#313134"/>'+sources.map((n,i)=>
    `<rect x="${i*40+10}" y="${57-n/peak*48}" width="20" height="${n/peak*48}" fill="${['#e0e0e3','#9b9ba0','#6d6e75'][i]}"/>`).join('');
  $('source-note').textContent=`分级 ${sources[0]} · 情节 ${sources[1]} · 日记 ${sources[2]}`;
}

function approachHeading(hub, origins){
  let x=0,y=0;
  for(const start of origins){
    const dx=start.x-hub.x,dy=start.y-hub.y,length=Math.hypot(dx,dy);
    if(length<1)continue;
    x+=dx/length;y+=dy/length;
  }
  const length=Math.hypot(x,y);
  return length>0.35?{x:x/length,y:y/length}:null;
}

function traceRoute(start,end,heading){
  const dx=start.x-end.x,dy=start.y-end.y,length=Math.hypot(dx,dy);
  if(length<1)return;
  const ux=dx/length,uy=dy/length;
  const alignment=heading?ux*heading.x+uy*heading.y:0;
  // Follow the direct heading for most of the trip. Nearby incoming
  // routes share an approach, while opposite arrivals keep their side.
  const merge=Math.max(0,alignment)*0.75;
  const hx=ux*(1-merge)+(heading?.x??ux)*merge;
  const hy=uy*(1-merge)+(heading?.y??uy)*merge;
  const approach=Math.min(length*0.34,105*pixelScale);
  const bank=Math.min(length*0.065,14*pixelScale)*(ux<0?-1:1);
  ctx.moveTo(start.x,start.y);
  ctx.bezierCurveTo(start.x-dx*0.62,start.y-dy*0.62,
    end.x+hx*approach-uy*bank,end.y+hy*approach+ux*bank,end.x,end.y);
}

function draw(t){
  ctx.clearRect(0,0,W,H);
  ctx.globalAlpha=0.32;
  ctx.fillStyle='#d4d8df';
  if(dustPath){
    ctx.save();
    ctx.translate(panX*0.12,panY*0.12);
    ctx.fill(dustPath);
    ctx.restore();
  }
  ctx.globalAlpha = 1;
  ctx.lineWidth = pixelScale*0.8;
  const view=camera();
  const positions=new Map(visibleNodes.map(n=>[n,project(n,view)]));
  if(hovered&&hoverPoint&&!dragging&&!selected){
    const point=positions.get(hovered);
    if(!point||Math.hypot(point.x-hoverPoint.x,point.y-hoverPoint.y)>Math.max(13,hovered.r*3)*pixelScale)clearHover();
  }
  const focus=selected||hovered;
  const connected=new Set();
  const focusedEdges=focus?visibleEdges.filter(({a,b})=>a===focus||b===focus):[];
  const hub=positions.get(focus);
  const heading=hub?approachHeading(hub,focusedEdges.map(({a,b})=>positions.get(a===focus?b:a))):null;
  const showAll=$('show-all-routes').checked;
  for(const highlight of [false,true]){
    if(!highlight&&!showAll)continue;
    ctx.globalAlpha=highlight?0.86:focus?0.09:0.25;
    ctx.lineWidth=pixelScale*(highlight?1.05:0.72);
    for(const [kind,{color}] of Object.entries(RELATIONS)){
      ctx.strokeStyle=highlight?'#edf2fa':color;
      ctx.beginPath();
      for(const {a,b,kind:relation} of highlight?focusedEdges:visibleEdges){
        if(relation!==kind||Boolean(focus&&(focus===a||focus===b))!==highlight)continue;
        if(highlight){connected.add(a);connected.add(b);}
        if(highlight)traceRoute(positions.get(a===focus?b:a),hub,heading);
        else traceRoute(positions.get(a),positions.get(b),null);
      }
      ctx.stroke();
    }
  }
  const size=Number($('star-size').value);
  const tinted=$('emotion-tint').checked;
  const depthOrder=[...visibleNodes].sort((a,b)=>positions.get(a).depth-positions.get(b).depth);
  for(const n of depthOrder){
    const c = tinted?emotionColor(emotionOf(n)):'#e7ebf2';
    const {x,y,perspective}=positions.get(n);
    const r = n.r*pixelScale*Math.min(zoom,1.6)*perspective*size;
    const tw = 0.73+0.14*Math.sin(t/700+n.ph);
    const dim=selected&&n!==selected&&!connected.has(n);
    ctx.globalAlpha = dim?0.15:tw;
    const glow=starGlow(c);
    const radius=r*3.25;
    ctx.drawImage(glow,x-radius,y-radius,radius*2,radius*2);
    ctx.globalAlpha=dim?0.2:0.86;
    ctx.drawImage(starGlow('#f0f2f7'),x-radius*0.59,y-radius*0.59,radius*1.18,radius*1.18);
    if(n===selected || n===hovered){
      ctx.globalAlpha=1; ctx.strokeStyle=c; ctx.lineWidth=pixelScale;
      ctx.beginPath(); ctx.arc(x,y, r*4+Math.sin(t/250)*pixelScale*2, 0, 7); ctx.stroke();
    }
    ctx.globalAlpha=1;
  }
  if(labels)drawLabels(positions,depthOrder,focus,connected);
}
function drawLabels(positions,depthOrder,focus,connected){
  const placed=[];
  const candidates=focus?[focus,...depthOrder.reverse().filter(n=>n!==focus)]:depthOrder.reverse();
  const limit=Math.min(14,Math.max(5,Math.floor(W/(65*pixelScale))));
  for(const n of candidates){
    if(placed.length>=limit||!n.label||(focus&&n!==focus&&!connected.has(n)))continue;
    const {x,y,perspective}=positions.get(n);
    const font=Math.round(Math.max(10,Math.min(20,14*perspective*Math.sqrt(zoom))))*pixelScale;
    ctx.font=`600 ${font}px "Microsoft YaHei", sans-serif`;
    const cache=n.labelWidths??=(new Map());
    if(!cache.has(font))cache.set(font,ctx.measureText(n.label).width);
    const width=cache.get(font);
    const left=x-width/2,top=y-font-13*pixelScale;
    if(left<4||left+width>W-4||top<5||top+font>H-5)continue;
    if(placed.some(p=>left<p.right+8&&left+width>p.left-8&&top<p.bottom+5&&top+font>p.top-5))continue;
    placed.push({left,top,right:left+width,bottom:top+font});
    ctx.globalAlpha=n===focus?1:0.75;
    ctx.fillStyle='#e1e4e9';ctx.textBaseline='top';ctx.fillText(n.label,left,top);
  }
  ctx.globalAlpha=1;
}
const glowCache=new Map();
function starGlow(color){
  if(!glowCache.has(color)){
    const sprite=document.createElement('canvas');
    sprite.width=sprite.height=96;
    const g=sprite.getContext('2d'), halo=g.createRadialGradient(48,48,0,48,48,48);
    halo.addColorStop(0,color); halo.addColorStop(0.18,color); halo.addColorStop(1,'transparent');
    g.fillStyle=halo; g.fillRect(0,0,96,96);
    g.fillStyle=color; g.beginPath(); g.arc(48,48,8,0,Math.PI*2); g.fill();
    g.fillStyle='#fff'; g.beginPath(); g.arc(48,48,2.8,0,Math.PI*2); g.fill();
    glowCache.set(color,sprite);
  }
  return glowCache.get(color);
}
function moveStars(t){
  const dt=motionTime===null?16:Math.min(50,t-motionTime);
  motionTime=t;
  const follow=1-Math.exp(-dt/42);
  let moving=false;
  if(dragging&&dragTarget){
    const dx=(dragTarget.x-dragging.x)*follow, dy=(dragTarget.y-dragging.y)*follow;
    for(const n of nodes){
      if(n===dragging)continue;
      const distance=Math.hypot(n.x-dragging.x,n.y-dragging.y);
      const influence=Math.max(0,1-distance/0.32);
      if(!reducedMotion.matches){
        n.ox+=dx*influence*0.72;
        n.oy+=dy*influence*0.72;
      }
    }
    dragging.x+=dx; dragging.y+=dy;
    dragging.z+=(dragTarget.z-dragging.z)*follow;
  }
  for(const n of nodes){
    n.ox*=Math.exp(-dt/210); n.oy*=Math.exp(-dt/210);
    if(Math.abs(n.ox)+Math.abs(n.oy)<0.00015)n.ox=n.oy=0;
    else moving=true;
    if(!selected&&!dragging&&!reducedMotion.matches){
      n.fx=Math.sin(t/1900+n.ph)*0.0028;
      n.fy=Math.cos(t/2300+n.ph*1.7)*0.004;
    }
  }
  return moving;
}
function advanceZoom(t){
  const elapsed=lastFrame===null?16:Math.min(50,t-lastFrame);
  lastFrame=t;
  if(zoom===targetZoom)return;
  const next=Math.abs(targetZoom-zoom)<0.001
    ? targetZoom
    : zoom+(targetZoom-zoom)*(1-Math.exp(-elapsed/85));
  const ratio=next/zoom;
  panX=W/2+(panX-W/2)*ratio;
  panY=H/2+(panY-H/2)*ratio;
  zoom=next;
}
function requestDraw(){
  clearTimeout(idleTimer);
  idleTimer=null;
  if(document.hidden)return;
  if(frameId===null)frameId=requestAnimationFrame(loop);
}
function loop(t){
  frameId=null;
  const elapsed=orbitTime===null?0:Math.min(55,t-orbitTime);
  orbitTime=t;
  const active=document.hasFocus()&&!document.hidden;
  const orbiting=active&&!flat&&orbit&&!selected&&!dragging&&!panning&&visibleNodes.length>0;
  if(orbiting)yaw=(yaw+elapsed*0.000066)%(2*Math.PI);
  advanceZoom(t);
  const moving=moveStars(t);
  draw(t);
  if(orbiting||dragging||moving||zoom!==targetZoom)requestDraw();
  else {
    lastFrame=null;
    orbitTime=null;
    if(active&&!selected&&visibleNodes.length&&!reducedMotion.matches)idleTimer=setTimeout(requestDraw,72);
  }
}
document.addEventListener('visibilitychange',()=>{
  motionTime=null;
  orbitTime=null;
  requestDraw();
});
reducedMotion.addEventListener('change',requestDraw);
window.addEventListener('focus',requestDraw);
window.addEventListener('blur',()=>{
  clearTimeout(idleTimer);
  idleTimer=null;
  orbitTime=null;
  dragging=dragTarget=panning=null;
});

cv.addEventListener('wheel', ev=>{
  ev.preventDefault();
  clearHover();
  const unit=ev.deltaMode===1?16:ev.deltaMode===2?cv.clientHeight:1;
  const delta=Math.max(-240,Math.min(240,ev.deltaY*unit));
  targetZoom=Math.min(2.8,Math.max(0.35,targetZoom*Math.exp(-delta*0.0012)));
  requestDraw();
}, {passive:false});

cv.addEventListener('mousedown', ev=>{
  if(ev.button!==0)return;
  const rect = cv.getBoundingClientRect();
  const mx=(ev.clientX-rect.left)*W/rect.width, my=(ev.clientY-rect.top)*H/rect.height;
  if(ev.shiftKey&&!flat){
    hovered=null;
    panning={mx,my,rotate:true};
    return;
  }
  hovered=pickStar(mx,my);
  if(hovered){
    dragging=hovered;
    dragMoved=0;
    const view=project(dragging);
    dragTarget={x:dragging.x,y:dragging.y,z:dragging.z,view,dx:view.x-mx,dy:view.y-my};
  }
  else { panning = {mx, my}; }
});
let dragMoved = 0;
cv.addEventListener('mousemove', ev=>{
  const rect = cv.getBoundingClientRect();
  const sx=(ev.clientX-rect.left)*W/rect.width, sy=(ev.clientY-rect.top)*H/rect.height;
  if(panning){
    if(panning.rotate){
      yaw+=(sx-panning.mx)/W*3;
      pitch=Math.max(-1.2,Math.min(1.2,pitch+(sy-panning.my)/H*2));
    }else{
      panX+=sx-panning.mx;
      panY+=sy-panning.my;
    }
    panning.mx=sx;panning.my=sy;requestDraw();return;
  }
  if(dragging){
    const {x,y,z}=dragCoordinates(sx+dragTarget.dx,sy+dragTarget.dy,dragTarget.view);
    dragMoved+=Math.hypot(x-dragTarget.x,y-dragTarget.y);
    dragTarget.x=x; dragTarget.y=y; dragTarget.z=z;
    requestDraw();
    return;
  }
  const previousHover=hovered;
  hoverPoint={x:sx,y:sy};
  hovered=pickStar(sx,sy);
  if(hovered===previousHover)return;
  requestDraw();
  const tip = document.getElementById('tip');
  if(hovered && !selected){
    tip.style.display='block';
    const point=project(hovered);
    const starX=point.x*rect.width/W, starY=point.y*rect.height/H;
    let tx=starX+16, ty=starY+12;
    const label=emotionOf(hovered);
    tip.innerHTML = '<b style="color:'+emotionColor(label)+'">'+esc(label)+'</b> <span class="d">'+esc((hovered.date||'').slice(0,10))+'</span><br>'+esc(memorySummary(hovered));
    const tw2 = tip.offsetWidth, th2 = tip.offsetHeight;
    if(tx + tw2 > rect.width - 8) tx = starX - tw2 - 16;   // 靠右→向内(左)弹
    if(tx < 8) tx = 8;
    if(ty + th2 > rect.height - 8) ty = starY - th2 - 12;  // 靠下→向上弹
    if(ty < 8) ty = 8;
    tip.style.left = tx+'px'; tip.style.top = ty+'px';
    cv.style.cursor='grab';
  } else { tip.style.display='none'; if(!dragging && !panning) cv.style.cursor = hovered?'grab':'default'; }
});
cv.addEventListener('mouseleave',()=>{
  if(dragging||!hovered)return;
  clearHover();
  requestDraw();
});
function clearHover(){
  hovered=null;
  hoverPoint=null;
  $('tip').style.display='none';
  cv.style.cursor='default';
}
window.addEventListener('mouseup', ev=>{
  const wasInteracting=dragging||panning;
  if(dragging && dragMoved < 0.02){ selectNode(dragging.id, false); }
  else if(dragging){ requestDraw(); }
  dragging=null; dragTarget=null; panning=null;
  if(wasInteracting)requestDraw();
});

function selectNode(id, center){
  const n = byId[id]; if(!n) return;
  selected = n;
  $('tip').style.display='none';
  for(const item of document.querySelectorAll('.mi'))item.classList.toggle('on',item.dataset.id===id);
  if(center){ const point=project(n);panX+=W/2-point.x;panY+=H/2-point.y; }
  openDetail(n);
  requestDraw();
}
function closeDetail(){
  $('facts-dialog').close();
  document.getElementById('detail').style.display='none';
  selected = null;
  hovered=null;
  requestDraw();
  document.querySelectorAll('.mi.on').forEach(x=>x.classList.remove('on'));
}
function openDetail(n){
  const d = document.getElementById('detail');
  const core=n.src==='core';
  const editable=core||n.source_id!=null;
  $('d-title').textContent='记忆详情 · '+({core:'核心记忆',living:'情节记忆',diary:'璃笺日记'})[n.src];
  $('d-meta').textContent=[(n.date||'').slice(0,10),n.provenance,emotionOf(n),core?(LV_NAME[n.level]||'核心'):editable?'可编辑':'旧记录 · 只读'].filter(Boolean).join(' · ');
  const related=edges.filter(e=>e.a===n||e.b===n);
  $('d-links').textContent=related.map(e=>{
    const other=e.a===n?e.b:e.a;
    const evidence=Object.entries(e.reasons).map(([kind,values])=>RELATIONS[kind].label+' '+values.join('、'));
    return evidence.join(' / ')+' · '+other.text.replace(/\s+/g,' ').slice(0,24);
  }).join('\n');
  $('d-text').value = memorySummary(n);
  $('d-text').readOnly = !editable;
  $('d-facts').hidden = !n.facts?.length;
  $('d-level').style.display = core?'':'none';
  $('d-save').style.display = editable?'':'none';
  $('d-del').style.display = editable?'':'none';
  $('d-archive').style.display=editable&&n.src==='diary'?'':'none';
  if(core) $('d-level').value = n.level||'core';
  $('d-msg').style.display='none';
  d.dataset.id = n.id; d.dataset.src = n.src;
  d.style.display='block';
  const rect = cv.getBoundingClientRect();
  const point=project(n);
  const starX=point.x*rect.width/W, starY=point.y*rect.height/H;
  let lx=starX+20, ly=starY-20;
  const dw=d.offsetWidth, dh=d.offsetHeight;
  if(lx + dw > rect.width - 10) lx = starX - dw - 20;
  if(lx < 10) lx = 10;
  ly=Math.max(10,Math.min(ly,rect.height-dh-10));
  d.style.left = lx+'px'; d.style.top = ly+'px';
}
document.getElementById('d-close').onclick = closeDetail;
$('d-facts').onclick=()=>{
  const facts=selected?.facts;
  if(!facts?.length)return;
  $('facts-list').replaceChildren(...facts.map(fact=>{
    const item=document.createElement('li');
    item.textContent=fact;
    return item;
  }));
  $('facts-dialog').showModal();
};
let changingMemory=false;
async function changeMemory(action){
  const n=byId[$('detail').dataset.id];
  if(changingMemory||!n)return;
  const edit=action==='edit';
  if(!edit&&!confirm(action==='archive'?'归档这篇日记并从星图移除？':
    n.src==='diary'?'永久删除这篇璃笺日记？删除前会保存本机备份。':'删除这条记忆？'))return;
  changingMemory=true;
  const msg=$('d-msg');
  msg.style.display='block';
  msg.textContent='正在处理…';
  const source=n.src==='core'?{ts:n.date,old:n.text,content:n.text}:
    {id:n.id,src:n.src,version:n.version};
  const summary=$('d-text').value;
  const suffix=n.summary?n.text.slice(n.summary.length):'';
  const body=edit?{...source,new_text:summary.trim()?summary+suffix:summary,new_level:$('d-level').value}:source;
  try{
    const r=await fetch('/memory/'+action,{method:'POST',
      headers:{'Content-Type':'application/json','X-Wallpaper-Token':window.WALLPAPER_BRIDGE_TOKEN},
      body:JSON.stringify(body)});
    const result=await r.json();
    if(!r.ok||result.status!=='ok')throw Error(result.message||'操作失败');
    await loadData();
  }catch(error){
    msg.style.color='#f38ba8';
    msg.textContent=error.message;
  }finally{changingMemory=false;}
}
$('d-save').onclick=()=>changeMemory('edit');
$('d-archive').onclick=()=>changeMemory('archive');
$('d-del').onclick=()=>changeMemory('delete');
document.getElementById('btn-refresh').onclick = loadData;
$('star-search').oninput=event=>{
  search=event.target.value.trim().toLowerCase();
  if(DATA)applyFilters();
};
function resetView(){
  yaw=0.28;pitch=0.31;panX=panY=0;zoom=targetZoom=1;
  closeDetail();
}
function setView(isFlat){
  flat=isFlat;
  $('view-space').setAttribute('aria-pressed',String(!flat));
  $('view-flat').setAttribute('aria-pressed',String(flat));
  renderOrbit();
  resetView();
}
$('view-space').onclick=()=>setView(false);
$('view-flat').onclick=()=>setView(true);
$('reset-view').onclick=resetView;
$('toggle-labels').onclick=()=>{
  labels=!labels;
  $('toggle-labels').setAttribute('aria-pressed',String(labels));
  requestDraw();
};
function showDashboard(open){
  $('dashboard').hidden=!open;
  $('workspace').classList.toggle('dashboard-hidden',!open);
  $('toggle-dashboard').setAttribute('aria-pressed',String(open));
}
$('toggle-dashboard').onclick=()=>showDashboard($('dashboard').hidden);
if(matchMedia('(max-width:750px)').matches)showDashboard(false);
for(const id of ['show-all-routes','emotion-tint','star-size'])$(id).oninput=requestDraw;
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!$('facts-dialog').open&&selected)closeDetail();
});

resize(); loadData();
</script>
</body></html>"""


