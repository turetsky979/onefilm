#!/usr/bin/env python3
"""ONEFILM - one-click download from a Baidu group file library to a local server.

- Search: Baidu group file-library live API (basembox/group/search), no index.
- Download: transfer selected group item into own netdisk, then curl via OpenList.
- Folder: recursively download every file (video + subtitles + artwork, etc.).
- Cleanup: delete the temporary transferred copy after a batch finishes.
Python stdlib + curl only.

All paths are relative to this file's directory by default and can be
overridden with environment variables (see docs/CONFIGURATION.md).
"""
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.environ.get("ONEFILM_DATA_DIR", os.path.join(BASE_DIR, "data"))

CONF_PATH = os.environ.get("ONEFILM_CONF", os.path.join(BASE_DIR, "config.json"))
COOKIE_PATH = os.environ.get("ONEFILM_COOKIE", os.path.join(BASE_DIR, "baidu_cookie.txt"))
GIDS_PATH = os.environ.get("ONEFILM_GIDS", os.path.join(DEFAULT_DATA_DIR, "tasks.json"))
BROWSE_PATH = os.environ.get("ONEFILM_BROWSE", os.path.join(DEFAULT_DATA_DIR, "browse.json"))
BROWSE_TTL = 7200  # seconds: browse-only sessions are forgotten after this
INDEX_PATH = os.environ.get("ONEFILM_INDEX", os.path.join(BASE_DIR, "web", "index.html"))
XFER_DEBUG = os.environ.get("ONEFILM_DEBUG_LOG", os.path.join(DEFAULT_DATA_DIR, "transfer-debug.log"))
CURL_BIN = os.environ.get("ONEFILM_CURL", "/usr/bin/curl")
OL_RESTART_CMD = os.environ.get("ONEFILM_OL_RESTART", "")  # e.g. "/etc/init.d/openlist restart"

os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)

with open(CONF_PATH, encoding="utf-8") as f:
    CONF = json.load(f)

OL_BASE = CONF["openlist_base"]
OL_TOKEN = CONF["openlist_token"]
LIB_BD = CONF.get("library_baidu_path", "/_电影库")
TARGET = CONF["target_dir"]
PORT = int(CONF.get("port", 8088))
GID = str(CONF.get("group_id") or "").strip()

# Baidu Web-protocol signing constants. Copy the current values from the
# Baidu Netdisk web front-end; see docs/CONFIGURATION.md. They are not
# account credentials. Overridable via config so future changes are painless.
GROUP_SIGN_SALT = CONF.get("group_sign_salt", "")
DIRSIZE_SK = CONF.get("dirsize_sk", "")

if not GID:
    raise SystemExit("config.json: 'group_id' is required")
if not GROUP_SIGN_SALT or not DIRSIZE_SK:
    raise SystemExit("config.json: 'group_sign_salt' and 'dirsize_sk' are required")

SEARCH_URL = "https://pan.baidu.com/basembox/group/search?clienttype=0&app_id=250528&web=1"
XFER_URL = "https://pan.baidu.com/mbox/msg/transfer?clienttype=0&app_id=250528&web=1"
SHAREINFO_URL = "https://pan.baidu.com/mbox/msg/shareinfo?clienttype=0&app_id=250528&web=1"
LIST_URL = "https://pan.baidu.com/api/list?clienttype=0&app_id=250528&web=1"
FM_URL = "https://pan.baidu.com/api/filemanager"
TOKEN_URL = ("https://pan.baidu.com/api/gettemplatevariable?clienttype=0&app_id=250528"
             "&web=1&fields=%5B%22bdstoken%22%2C%22uk%22%5D")
DIRSIZE_URL = "https://pan.baidu.com/sharedir/file/dirsize?clienttype=0&app_id=250528&web=1"
DIRSIZE_TASK_URL = "https://pan.baidu.com/sharedir/file/dirsizetask?clienttype=0&app_id=250528&web=1"

BD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".rmvb", ".ts", ".m2ts", ".flv", ".wmv", ".iso", ".webm")

GID_LOCK = threading.Lock()
TRANSFER_LOCK = threading.Lock()
SYNC_STATE = {"running": False, "last": 0, "message": "", "added": 0}
BD_COOKIE = ""
BD_TOKEN = ""
BD_UK = ""
DIRSIZE_CACHE = {}   # fsid(str) -> size bytes
DIRSIZE_LOCK = threading.Lock()


# ---------------- persistence ----------------
def load_gids():
    try:
        with open(GIDS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
            return {g: {"path": "", "out": "", "retries": 0, "status": ""} for g in d}
    except Exception:
        return {}


def save_gids(gids):
    try:
        with open(GIDS_PATH, "w", encoding="utf-8") as f:
            json.dump(gids, f, ensure_ascii=False)
    except Exception:
        pass


def load_browse():
    try:
        with open(BROWSE_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_browse(d):
    try:
        with open(BROWSE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------- Baidu HTTP ----------------
def load_baidu():
    global BD_COOKIE, BD_TOKEN
    try:
        BD_COOKIE = open(COOKIE_PATH, encoding="utf-8").read().strip()
    except Exception:
        BD_COOKIE = ""
    BD_TOKEN = ""
    ensure_token()


def ensure_token():
    global BD_TOKEN, BD_UK
    if BD_TOKEN:
        return BD_TOKEN
    req = urllib.request.Request(TOKEN_URL, headers={
        "Cookie": BD_COOKIE, "User-Agent": BD_UA, "Referer": "https://pan.baidu.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    result = d.get("result") or {}
    BD_TOKEN = result.get("bdstoken", "")
    BD_UK = str(result.get("uk") or "")
    return BD_TOKEN


def baidu_get(url):
    req = urllib.request.Request(url, headers={
        "Cookie": BD_COOKIE, "User-Agent": BD_UA, "Referer": "https://pan.baidu.com/"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def baidu_post(url, params=None, query=None, xhr=False):
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    full = url
    if query:
        full += ("&" if "?" in full else "?") + urllib.parse.urlencode(query)
    headers = {
        "Cookie": BD_COOKIE, "User-Agent": BD_UA, "Referer": "https://pan.baidu.com/",
        "Content-Type": "application/x-www-form-urlencoded"}
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(full, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def bd_list_all(dir_path):
    out = []
    page = 1
    while page <= 80:
        d = baidu_get(LIST_URL + "&" + urllib.parse.urlencode({
            "dir": dir_path, "order": "name", "desc": 0,
            "num": 1000, "page": page, "showparent": 1}))
        if d.get("errno") != 0:
            raise RuntimeError("百度列目录失败 errno=%s" % d.get("errno"))
        batch = d.get("list") or []
        for x in batch:
            name = x.get("server_filename") or x.get("path", "").rstrip("/").split("/")[-1]
            out.append({
                "name": name,
                "path": x.get("path", ""),
                "isdir": bool(x.get("isdir")),
                "size": int(x.get("size") or 0),
                "mtime": int(x.get("mtime") or 0),
                "fs_id": str(x.get("fs_id", "")),
            })
        if len(batch) < 1000:
            break
        page += 1
    return out


def bd_list(dir_path):
    return bd_list_all(dir_path)


# ---------------- folder size (Baidu sharedir dirsize) ----------------
def dirsize_sign(owner_uk, fsids, taskid=None, ts=None):
    ts = ts if ts is not None else int(time.time())
    if taskid is not None:
        raw = "%s|%s|%s|%d|%s" % (BD_UK, owner_uk, taskid, ts, DIRSIZE_SK)
    else:
        raw = "%s|%s|%s|%d|%s" % (BD_UK, owner_uk, ",".join(str(x) for x in fsids), ts, DIRSIZE_SK)
    return hashlib.md5(raw.encode("utf-8")).hexdigest(), ts


def _dirsize_query(owner_uk, fsids):
    """Submit a dirsize task and poll until success; return {fsid: size}."""
    ensure_token()
    ts0 = int(time.time())
    sign, _ = dirsize_sign(owner_uk, fsids, ts=ts0)
    r = baidu_post(DIRSIZE_URL, {
        "owner_uk": str(owner_uk),
        "fsid_list": json.dumps([int(x) for x in fsids]),
    }, query={"bdstoken": BD_TOKEN, "time": ts0, "sign": sign})
    if r.get("errno") != 0:
        raise RuntimeError("dirsize submit errno=%s" % r.get("errno"))
    taskid = str((r.get("data") or {}).get("taskid") or "")
    if not taskid:
        raise RuntimeError("dirsize 无 taskid")
    for _ in range(30):
        time.sleep(1)
        ts1 = int(time.time())
        sign, _ = dirsize_sign(owner_uk, [], taskid=taskid, ts=ts1)
        p = baidu_post(DIRSIZE_TASK_URL, {
            "owner_uk": str(owner_uk), "taskid": taskid,
        }, query={"bdstoken": BD_TOKEN, "time": ts1, "sign": sign})
        data = p.get("data") or {}
        st = data.get("status")
        if st == "success":
            return {str(x.get("fsid")): int(x.get("size") or 0)
                    for x in (data.get("dirlist") or [])}
        if st == "failed":
            raise RuntimeError("dirsize task failed")
    raise RuntimeError("dirsize 任务超时")


def folder_sizes(items):
    """Fill sizes for folder items {fs_id, uk}; return {fsid: bytes}.

    Cached in memory. Groups by owner uk; submits in batches to respect limits.
    """
    want = {}  # fsid -> owner_uk
    for x in items or []:
        fsid = str(x.get("fs_id") or "")
        uk = str(x.get("uk") or "")
        if fsid and uk:
            want[fsid] = uk
    with DIRSIZE_LOCK:
        todo = {f: u for f, u in want.items() if f not in DIRSIZE_CACHE}
    if todo:
        by_uk = {}
        for fsid, uk in todo.items():
            by_uk.setdefault(uk, []).append(fsid)
        for uk, fsids in by_uk.items():
            for i in range(0, len(fsids), 100):
                batch = fsids[i:i + 100]
                try:
                    got = _dirsize_query(uk, batch)
                except Exception:
                    got = {}
                with DIRSIZE_LOCK:
                    for fsid in batch:
                        DIRSIZE_CACHE[fsid] = int(got.get(fsid) or 0)
    with DIRSIZE_LOCK:
        return {f: DIRSIZE_CACHE.get(f, 0) for f in want}


# ---------------- group file-library search ----------------
def group_sign(term):
    h = hashlib.md5((GROUP_SIGN_SALT + "_" + GID + term).encode("utf-8")).hexdigest()
    return base64.b64encode(urllib.parse.quote(h).encode("utf-8")).decode("ascii")


def bd_group_search(keyword):
    """Real-time search inside the group's own file library (not personal disk)."""
    payload = json.dumps(
        {"gid": [GID], "key_word": keyword, "sign": group_sign(keyword)},
        ensure_ascii=False, separators=(",", ":"))
    d = baidu_post(SEARCH_URL, {"data": payload})
    if d.get("errno") != 0:
        raise RuntimeError("群文件库搜索失败 errno=%s" % d.get("errno"))
    out = []
    for x in d.get("result") or []:
        out.append({
            "name": x.get("server_filename", ""),
            "path": urllib.parse.unquote(x.get("path", "")),
            "isdir": str(x.get("is_dir")) == "1",
            "size": int(x.get("size") or 0),
            "fs_id": str(x.get("fsid") or ""),
            "msgId": str(x.get("msgId") or ""),
            "uk": str(x.get("uk") or ""),
            "source": x.get("uname") or x.get("chat_name") or "",
            "ctime": int(x.get("msg_ctime") or x.get("cTime") or 0),
        })
    return out


def xdbg(event, **kw):
    """Append one diagnostic JSON line; never affect normal behaviour."""
    try:
        rec = {"t": time.time(), "event": event}
        rec.update(kw)
        with open(XFER_DEBUG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def probe_nested(item, name):
    """Inspect likely nested landing paths under LIB_BD without changing logic."""
    result = {}
    parts = [p for p in ((item or {}).get("path") or "").split("/") if p]
    candidates = []
    for i in range(1, min(len(parts), 5)):
        candidates.append(LIB_BD + "/" + "/".join(parts[:i]))
    if parts:
        candidates.append(LIB_BD + "/" + "/".join(parts))
    if name:
        candidates.append(LIB_BD + "/" + name)
    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        try:
            rows = bd_list_all(c)
            result[c] = [{"path": x["path"], "name": x["name"],
                          "isdir": x["isdir"], "size": x["size"]}
                         for x in rows[:200]]
        except Exception as e:
            result[c] = "ERR: " + str(e)
    return result


def group_transfer(item):
    """Transfer one group-search hit into the already-existing library root."""
    ensure_token()
    fsid = item.get("fs_id") or item.get("fsid")
    if not fsid or not item.get("msgId") or not item.get("uk"):
        raise RuntimeError("搜索结果缺少转存所需 ID")
    params = {
        "bdstoken": BD_TOKEN,
        "from_uk": str(item["uk"]),
        "msg_id": str(item["msgId"]),
        "path": LIB_BD,
        "ondup": "newcopy",
        "async": "4",
        "fs_ids": json.dumps([int(fsid)]),
        "type": "2",
        "gid": GID,
    }
    r = baidu_post(XFER_URL, params)
    xdbg("transfer_response", item={"name": item.get("name"), "path": item.get("path"),
                                    "fs_id": fsid, "msgId": item.get("msgId"),
                                    "uk": item.get("uk")},
         params={k: v for k, v in params.items() if k != "bdstoken"}, response=r)
    eno = r.get("errno")
    # Baidu web returns -10 with target_file_nums>0 for accepted async transfers.
    if eno not in (0, -10):
        raise RuntimeError("群文件转存失败 errno=%s" % eno)
    if eno == -10 and int(r.get("target_file_nums") or 0) <= 0:
        raise RuntimeError("群文件转存未创建任何文件")
    return r


def norm_stage_name(s):
    """Ignore Baidu's (1)/(2) duplicate suffix when matching staged items."""
    return re.sub(r"\s*\(\d+\)\s*$", "", s or "").strip()


def stage_name_hit(actual, expected):
    a, b = norm_stage_name(actual), norm_stage_name(expected)
    if not a or not b:
        return False
    return a == b or a[:18] == b[:18] or b[:18] in a


def stage_candidate_parents(item):
    """Likely parents where Baidu keeps part of the original source structure.

    Baidu transfers a group hit into LIB_BD but often preserves the source
    path below the first component, e.g.
      /1117/影史最佳100部动画电影片单/2003 东京教父...
        -> /_电影库/影史最佳100部动画电影片单/2003 东京教父...
    so the new item may never appear at the LIB_BD top level.
    """
    parts = [p for p in ((item or {}).get("path") or "").split("/") if p]
    parents = set()
    if parts:
        parents.add(LIB_BD)
        if len(parts) > 1:
            parents.add(LIB_BD + "/" + "/".join(parts[1:-1]))
            parents.add(LIB_BD + "/" + "/".join(parts[:-1]))
        if len(parts) > 2:
            parents.add(LIB_BD + "/" + parts[-2])
    return sorted(p for p in parents
                  if p == LIB_BD or p.startswith(LIB_BD + "/"))


def snapshot_parents(parents, top_paths=None):
    out = {}
    for p in parents:
        if p == LIB_BD and top_paths is not None:
            out[p] = set(top_paths)
            continue
        try:
            out[p] = {x["path"] for x in bd_list_all(p)}
        except Exception:
            out[p] = set()
    return out


def wait_new_stage(before_paths, name, timeout=300, item=None,
                   before_children=None, candidate_parents=None):
    """Find a freshly transferred item at top level OR in likely nested paths."""
    base = norm_stage_name(name)
    deadline = time.time() + timeout
    parents = candidate_parents or stage_candidate_parents(item)
    before_children = before_children or {}
    while time.time() < deadline:
        try:
            now = bd_list_all(LIB_BD)
            fresh = [x for x in now if x["path"] not in before_paths]
            if fresh:
                xdbg("top_fresh", name=name, fresh=[
                    {"path": x["path"], "name": x["name"], "isdir": x["isdir"]}
                    for x in fresh])
                hits = [x for x in fresh if stage_name_hit(x["name"], base)]
                if hits:
                    return hits
        except Exception as e:
            xdbg("poll_error", name=name, error=str(e))
        for parent in parents:
            try:
                rows = bd_list_all(parent)
            except Exception as e:
                xdbg("parent_poll_error", name=name, parent=parent, error=str(e))
                continue
            before_set = before_children.get(parent) or set()
            hits = [x for x in rows
                    if x["path"] not in before_set
                    and stage_name_hit(x["name"], base)]
            if hits:
                xdbg("nested_stage_found", name=name, parent=parent, hits=[
                    {"path": x["path"], "name": x["name"], "isdir": x["isdir"]}
                    for x in hits])
                return hits
        time.sleep(2)
    final_probe = {}
    for parent in parents:
        try:
            rows = bd_list_all(parent)
            final_probe[parent] = [
                {"path": x["path"], "name": x["name"], "isdir": x["isdir"]}
                for x in rows if stage_name_hit(x["name"], base)]
        except Exception as e:
            final_probe[parent] = "ERR: " + str(e)
    xdbg("wait_timeout", name=name,
         source_path=(item or {}).get("path", ""),
         before_top=sorted(before_paths),
         final_parent_probe=final_probe,
         nested_probe=probe_nested(item, base))
    raise RuntimeError("转存副本未在库中出现，请稍后重试")


def collect_files(node):
    """Return every file under a staged item with a relative output path."""
    root_name = node.get("name") or os.path.basename(node["path"].rstrip("/"))
    root_name = root_name.replace("\\", "/").strip("/") or "movie"
    out = []

    def walk(path, rel, depth):
        if depth > 12 or len(out) > 5000:
            return
        for x in bd_list_all(path):
            child = (rel + "/" + x["name"]).replace("//", "/")
            if x["isdir"]:
                walk(x["path"], child, depth + 1)
            else:
                out.append({"path": x["path"], "rel": child,
                            "name": x["name"], "size": x["size"]})

    if node.get("isdir"):
        walk(node["path"], root_name, 0)
    else:
        out.append({"path": node["path"], "rel": root_name,
                    "name": root_name, "size": int(node.get("size") or 0)})
    return out


def browse_open(item):
    """Create a read-only browse session for a group folder, WITHOUT transferring.

    Folder children are listed live from Baidu's /mbox/msg/shareinfo using the
    original group share credentials. No temporary copy is created on the disk.
    """
    fsid = item.get("fs_id") or item.get("fsid") or ""
    if not (item.get("msgId") and item.get("uk") and fsid):
        raise RuntimeError("该文件夹缺少群文件凭证，无法直接浏览")
    bid = time.strftime("%Y%m%d%H%M%S") + "-" + \
        "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(5))
    root = {
        "path": item.get("path", ""),
        "name": item.get("name", ""),
        "isdir": True,
        "size": 0,
        "fs_id": str(fsid),
        "msgId": str(item["msgId"]),
        "uk": str(item["uk"]),
    }
    browses = load_browse()
    browses[bid] = {
        "name": item.get("name", ""),
        "root": root["path"],
        "fs_id": str(fsid),
        "msgId": str(item["msgId"]),
        "uk": str(item["uk"]),
        "created": time.time(),
    }
    save_browse(browses)
    return bid, root


def browse_list(bid, path=""):
    """List children of a group-shared folder via shareinfo (no transfer)."""
    browses = load_browse()
    entry = browses.get(bid)
    if not entry:
        raise RuntimeError("浏览会话已失效，请重新展开文件夹")
    out = []
    page = 1
    while page <= 100:
        params = {
            "from_uk": entry["uk"],
            "msg_id": entry["msgId"],
            "type": 2,
            "gid": GID,
            "num": 100,
            "page": page,
            "desc": 1,
            "limit": 100,
        }
        if not path or path.rstrip("/") == (entry.get("root") or "").rstrip("/"):
            params["fs_id"] = entry["fs_id"]
        else:
            params["path"] = path
        d = baidu_post(SHAREINFO_URL, params)
        eno = d.get("errno")
        if eno != 0:
            raise RuntimeError("读取群文件夹失败 errno=%s" % eno)
        records = d.get("records") or []
        for x in records:
            rel = x.get("path", "")
            out.append({
                "name": x.get("server_filename", ""),
                "path": rel,
                "isdir": str(x.get("isdir")) == "1",
                "size": int(x.get("size") or 0),
                "fs_id": str(x.get("fs_id") or ""),
                "msgId": entry["msgId"],
                "uk": entry["uk"],
            })
        if len(records) < 100:
            break
        page += 1
    return out


def browse_close(bid, force=False):
    """Drop a browse session. No staged copy exists any more, so just forget it."""
    browses = load_browse()
    if bid in browses:
        browses.pop(bid, None)
        save_browse(browses)
    return True


def cleanup_browses(tasks):
    """TTL cleanup for stale read-only browse sessions (no copy to delete)."""
    browses = load_browse()
    changed = False
    now = time.time()
    for bid, entry in list(browses.items()):
        if now - float(entry.get("created") or 0) < BROWSE_TTL:
            continue
        browses.pop(bid, None)
        changed = True
    if changed:
        save_browse(browses)


def bd_delete(paths):
    """Move temporary transfer copies out of the library (Baidu trash)."""
    safe = []
    for p in paths:
        if p.startswith(LIB_BD + "/") and p not in safe:
            safe.append(p)
    if not safe:
        return True
    ensure_token()
    query = {
        "opera": "delete", "async": 2, "clienttype": 0, "app_id": 250528,
        "web": 1, "bdstoken": BD_TOKEN, "channel": "chunlei",
        "newVerify": 1, "onnest": "fail",
    }
    body = urllib.parse.urlencode({
        "filelist": json.dumps(safe, ensure_ascii=False)}).encode("utf-8")
    req = urllib.request.Request(FM_URL + "?" + urllib.parse.urlencode(query),
        data=body, headers={
            "Cookie": BD_COOKIE, "User-Agent": BD_UA,
            "Referer": "https://pan.baidu.com/disk/home",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("errno") in (0, -9):
        return True
    raise RuntimeError("清理百度暂存副本失败 errno=%s" % d.get("errno"))


# ---------------- OpenList ----------------
def ol_path(bd_path):
    p = "1" + bd_path if bd_path.startswith("/") else "1/" + bd_path
    return p if p.startswith("/") else "/" + p


def ol_refresh(bd_path):
    """Ask OpenList to refresh a freshly transferred path."""
    data = json.dumps({"path": ol_path(bd_path), "password": "",
                       "page": 1, "per_page": 0, "refresh": True},
                      ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(OL_BASE + "/api/fs/list", data=data, headers={
            "Authorization": OL_TOKEN, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception:
        pass


def ol_link(bd_path):
    """Get a direct link; OpenList sometimes needs a cache kick after transfer."""
    data = json.dumps({"path": ol_path(bd_path), "password": ""},
                      ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(2):
        try:
            req = urllib.request.Request(OL_BASE + "/api/fs/link", data=data,
                headers={"Authorization": OL_TOKEN,
                         "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("code") == 200 and d.get("data"):
                return d["data"]["url"]
            last = d.get("message", "OpenList 取直链失败")
        except Exception as e:
            last = str(e)
        if attempt == 0:
            if OL_RESTART_CMD:
                try:
                    subprocess.run(OL_RESTART_CMD.split(), timeout=40,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            time.sleep(4)
            ol_refresh(bd_path)
    raise RuntimeError("OpenList 取直链失败：" + last[:160])


def _remote_size(url):
    req = urllib.request.Request(url, method="GET",
        headers={"Range": "bytes=0-0", "User-Agent": "pan.baidu.com"})
    with urllib.request.urlopen(req, timeout=25) as r:
        cr = r.headers.get("Content-Range", "")
        if "/" in cr:
            return int(cr.rsplit("/", 1)[1])
        return int(r.headers.get("Content-Length") or 0)


# ---------------- curl download engine ----------------
def _proc_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def prepare_batch_async(batch, items, placeholder_gids, errors_out):
    """Do slow transfer/list/link work in the background, then publish tasks.

    The HTTP handler only creates 'preparing' placeholders and returns at once;
    this worker replaces them with real download tasks when ready.
    """
    gids, errors, new_tasks, orphan_stages = [], [], {}, []
    stage_seen, file_seen = set(), set()
    try:
        with TRANSFER_LOCK:
            for item in items:
                staged_here = []
                try:
                    is_group = bool(item.get("msgId") or item.get("fs_id"))
                    if is_group:
                        before = {x["path"] for x in bd_list_all(LIB_BD)}
                        parents = stage_candidate_parents(item)
                        before_children = snapshot_parents(parents, before)
                        xdbg("before_top", name=item.get("name", ""),
                             paths=sorted(before))
                        xdbg("before_parents", name=item.get("name", ""),
                             parents=parents,
                             counts={p: len(v) for p, v in before_children.items()})
                        group_transfer(item)
                        staged = wait_new_stage(
                            before, item.get("name", ""), item=item,
                            before_children=before_children,
                            candidate_parents=parents)
                    else:
                        p = item.get("path", "")
                        if not p.startswith(LIB_BD + "/"):
                            raise RuntimeError("路径不在网盘素材库内：" + p)
                        staged = [{
                            "path": p,
                            "name": item.get("name") or os.path.basename(p),
                            "isdir": bool(item.get("isdir")),
                            "size": int(item.get("size") or 0),
                        }]
                    for st in staged:
                        if st["path"] in stage_seen:
                            continue
                        stage_seen.add(st["path"])
                        staged_here.append(st["path"])
                        ol_refresh(st["path"])
                        files = collect_files(st)
                        for f in files:
                            if f["path"] in file_seen:
                                continue
                            file_seen.add(f["path"])
                            gid = hashlib.md5((f["path"] + batch).encode()).hexdigest()[:16]
                            meta = {
                                "path": f["path"], "out": f["rel"],
                                "total": int(f.get("size") or 0),
                                "completed": 0, "speed": 0, "retries": 0,
                                "status": "", "snap_t": time.time(), "snap_s": 0,
                                "batch": batch,
                                "stage_paths": ([st["path"]] if is_group else []),
                                "auto_delete": bool(is_group),
                                "cleanup": "",
                            }
                            try:
                                start_curl(gid, meta)
                            except Exception as e:
                                errors.append("%s: %s" % (f["name"], str(e)[:120]))
                                continue
                            gids.append(gid)
                            new_tasks[gid] = meta
                except Exception as e:
                    errors.append(str(e)[:200])
                    orphan_stages.extend(staged_here)
    finally:
        errors_out["errors"] = errors
        errors_out["gids"] = gids
        errors_out["done"] = True

    if orphan_stages:
        try:
            bd_delete(orphan_stages)
        except Exception:
            pass

    # Atomically replace placeholders with real tasks (or mark them failed).
    with GID_LOCK:
        tasks = load_gids()
        for pgid in placeholder_gids:
            tasks.pop(pgid, None)
        if new_tasks:
            tasks.update(new_tasks)
        else:
            for pgid in placeholder_gids:
                tasks[pgid] = {
                    "path": "", "out": "准备失败", "total": 0, "completed": 0,
                    "speed": 0, "retries": 0, "status": "failed",
                    "error": "; ".join(errors)[:300] if errors else "准备失败",
                    "batch": batch, "cleanup": "done",
                }
        save_gids(tasks)
    cleanup_batches(load_gids())


def start_curl(gid, meta):
    path = meta.get("path", "")
    out = meta.get("out") or os.path.basename(path)
    dest = os.path.join(TARGET, out)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    total = int(meta.get("total") or 0)
    existing = os.path.getsize(dest) if os.path.exists(dest) else 0
    if total and existing >= total:
        meta.update(status="complete", completed=existing, total=total,
                    speed=0, pid=0)
        return meta

    ol_refresh(path)
    url = ol_link(path)
    if not total:
        try:
            total = _remote_size(url)
        except Exception:
            total = 0
    cmd = [CURL_BIN, "-s", "-L", "-k", "-A", "pan.baidu.com",
           "-C", "-", "--retry", "3", "--retry-delay", "2",
           "-o", dest, url]
    logf = os.path.join(DEFAULT_DATA_DIR, "curl-%s.log" % gid[:12])
    with open(logf, "ab") as lf:
        lf.write(("\n=== start %s ===\n" % time.strftime("%F %T")).encode())
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
    meta.update(pid=p.pid, out=out, status="", started=time.time(),
                total=total, completed=existing,
                snap_t=time.time(), snap_s=existing)
    return meta


def cleanup_batches(tasks):
    """Delete staged netdisk copies once every task in a batch is complete."""
    groups = {}
    for meta in tasks.values():
        b = meta.get("batch")
        if not b or not meta.get("stage_paths") or not meta.get("auto_delete"):
            continue
        groups.setdefault(b, []).append(meta)
    changed = False
    for batch, metas in groups.items():
        if any(m.get("cleanup") == "done" for m in metas):
            continue
        statuses = [m.get("status") for m in metas]
        if all(s in ("complete", "done") for s in statuses):
            paths = []
            for m in metas:
                for p in m.get("stage_paths") or []:
                    if p not in paths:
                        paths.append(p)
            try:
                bd_delete(paths)
                flag = "done"
            except Exception as e:
                flag = "failed:" + str(e)[:80]
            for m in metas:
                m["cleanup"] = flag
            changed = True
        elif all(s in ("complete", "done", "failed") for s in statuses):
            for m in metas:
                m["cleanup"] = "kept-failed"
            changed = True
    if changed:
        save_gids(tasks)


def watchdog():
    while True:
        time.sleep(2)
        try:
            tasks = load_gids()
        except Exception:
            continue
        changed = False
        for gid, meta in list(tasks.items()):
            if meta.get("status") in ("complete", "done", "failed", "preparing"):
                continue
            out = meta.get("out") or os.path.basename(meta.get("path", ""))
            dest = os.path.join(TARGET, out)
            try:
                cur = os.path.getsize(dest) if os.path.exists(dest) else 0
            except Exception:
                cur = 0
            total = int(meta.get("total") or 0)
            pid = meta.get("pid")
            if total and cur >= total:
                meta.update(status="complete", completed=cur, speed=0)
                changed = True
                continue
            if _proc_alive(pid):
                now = time.time()
                prev_t = float(meta.get("snap_t") or now)
                prev_s = int(meta.get("snap_s", 0))
                dt = max(now - prev_t, 0.001)
                meta.update(speed=int(max(0, cur - prev_s) / dt),
                            snap_t=now, snap_s=cur, completed=cur)
                changed = True
                continue
            retries = int(meta.get("retries") or 0)
            if retries >= 20 or not meta.get("path"):
                meta.update(status="failed", completed=cur)
                changed = True
                continue
            meta["retries"] = retries + 1
            try:
                start_curl(gid, meta)
                changed = True
            except Exception as e:
                meta.update(status="failed", completed=cur, error=str(e)[:200])
                changed = True
        if changed:
            save_gids(tasks)
        cleanup_batches(tasks)
        cleanup_browses(tasks)


# ---------------- legacy sync (kept for compatibility, not exposed) ----------------
def group_folders():
    pull = baidu_post("https://pan.baidu.com/imbox/msg/pull?clienttype=0&app_id=250528&web=1", {
        "pulltype": "1", "sids": json.dumps(["04_" + GID]), "needprofile": "1",
        "identity": "0", "showlink": "true", "showtransfer": "1"})
    out = []
    for rec in pull.get("sessions", [{}])[0].get("msgrecord", []):
        fl = rec.get("file_list") or []
        if rec.get("msgtype") == 100 and fl:
            f = fl[0]
            out.append({"msgid": str(rec["msgid"]), "fs_id": str(f["fs_id"]),
                        "from_uk": str(rec["from_uk"]), "name": f["server_filename"]})
    return out


def sync_folders():
    global SYNC_STATE
    if SYNC_STATE["running"]:
        return
    with GID_LOCK:
        SYNC_STATE.update(running=True, message="同步中…", added=0)
        try:
            existing = {x["name"] for x in bd_list_all(LIB_BD) if x["isdir"]}
            added = 0
            for fo in group_folders():
                if fo["name"] in existing:
                    continue
                try:
                    r = baidu_post(XFER_URL, {
                        "bdstoken": ensure_token(), "from_uk": fo["from_uk"],
                        "msg_id": fo["msgid"], "path": LIB_BD, "ondup": "newcopy",
                        "async": "4", "fs_ids": json.dumps([int(fo["fs_id"])]),
                        "type": "2", "gid": GID})
                    if r.get("errno") in (0, -10):
                        added += 1
                except Exception:
                    pass
            SYNC_STATE.update(running=False, last=time.time(), added=added,
                              message="完成：新增 %d 个" % added)
        except Exception as e:
            SYNC_STATE.update(running=False, message="同步失败：" + str(e)[:200])


# ---------------- HTTP handler ----------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self):
        # LAN-only panel: password removed by user request.
        return True

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            return self._serve_index()
        if not self._require_auth():
            return
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/info":
            self._json({"target_dir": TARGET, "library_baidu_path": LIB_BD})
            return
        if u.path == "/api/status":
            try:
                out = []
                for gid, meta in load_gids().items():
                    name = meta.get("out") or os.path.basename(meta.get("path", "")) or gid[:12]
                    out.append({
                        "gid": gid, "name": name,
                        "status": meta.get("status") or "downloading",
                        "completed": int(meta.get("completed") or 0),
                        "total": int(meta.get("total") or 0),
                        "speed": int(meta.get("speed") or 0),
                        "error": 1 if meta.get("status") == "failed" else 0,
                        "err_msg": meta.get("error", ""),
                        "retries": int(meta.get("retries") or 0),
                        "batch": meta.get("batch", ""),
                        "cleanup": meta.get("cleanup", ""),
                    })
                self._json({"tasks": out})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/search":
            kw = q.get("kw", [""])[0].strip()
            if not kw:
                self._json({"items": [], "kw": kw, "source": "group"})
                return
            try:
                items = bd_group_search(kw)
                self._json({"items": items, "kw": kw, "source": "group",
                            "hint": "群文件库实时搜索，共 %d 条" % len(items)})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/list":
            path = q.get("path", [LIB_BD])[0]
            bid = q.get("browse_id", [""])[0]
            try:
                if bid:
                    items = browse_list(bid, path)
                else:
                    items = bd_list_all(path)
                self._json({"items": items, "path": path})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/folder_videos":
            path = q.get("path", [""])[0]
            try:
                files = collect_files({"path": path, "name": os.path.basename(path),
                                       "isdir": True})
                files = [x for x in files if x["name"].lower().endswith(VIDEO_EXT)]
                self._json({"items": files})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/sync_status":
            self._json(SYNC_STATE)
            return
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        if u.path == "/api/login":
            # Kept for compatibility with old cached pages; no password needed.
            self._json({"ok": True})
            return
        if u.path == "/api/logout":
            self._json({"ok": True})
            return
        if not self._require_auth():
            return
        if u.path == "/api/browse":
            try:
                item = data.get("item") or {}
                bid, root = browse_open(item)
                self._json({"browse_id": bid, "root": root})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/dirsize":
            try:
                sizes = folder_sizes(data.get("items") or [])
                self._json({"sizes": sizes})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        if u.path == "/api/browse_close":
            bid = data.get("browse_id", "")
            if bid:
                browse_close(bid, force=bool(data.get("force")))
            self._json({"ok": True})
            return
        if u.path == "/api/download":
            # Respond immediately with placeholder tasks; the slow transfer /
            # list / link work happens in a background thread. This keeps the
            # "提交中…" phase out of the HTTP request (used to block up to 120s).
            items = data.get("items") or []
            if not items:
                items = [{"path": p, "name": os.path.basename(p)} for p in data.get("paths") or []]
            if not items:
                self._json({"error": "no items"}, 400)
                return
            batch = time.strftime("%Y%m%d-%H%M%S") + "-" + \
                "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4))
            placeholder_gids = []
            now = time.time()
            with GID_LOCK:
                tasks = load_gids()
                for i, item in enumerate(items):
                    pgid = "prep-" + batch + "-" + str(i)
                    placeholder_gids.append(pgid)
                    tasks[pgid] = {
                        "path": "", "out": item.get("name") or "准备中",
                        "total": 0, "completed": 0, "speed": 0, "retries": 0,
                        "status": "preparing", "batch": batch, "cleanup": "",
                        "created": now,
                    }
                save_gids(tasks)

            state = {"errors": [], "gids": [], "done": False}
            threading.Thread(
                target=prepare_batch_async,
                args=(batch, items, placeholder_gids, state),
                daemon=True,
            ).start()
            self._json({"gids": placeholder_gids, "errors": [], "batch": batch,
                        "dir": TARGET, "preparing": True})
            return
        if u.path == "/api/sync":
            threading.Thread(target=sync_folders, daemon=True).start()
            self._json({"ok": True})
            return
        if u.path == "/api/task_delete":
            gid = str(data.get("gid") or "")
            meta = None
            with GID_LOCK:
                tasks = load_gids()
                if gid in tasks:
                    meta = tasks.pop(gid)
                    save_gids(tasks)
            if meta:
                pid = meta.get("pid")
                if pid and _proc_alive(pid):
                    try:
                        os.kill(int(pid), 15)
                    except Exception:
                        pass
                logf = os.path.join(DEFAULT_DATA_DIR, "curl-%s.log" % str(gid)[:12])
                try:
                    os.remove(logf)
                except Exception:
                    pass
            self._json({"ok": True, "deleted": bool(meta)})
            return
        if u.path == "/api/task_clear_done":
            removed = []
            with GID_LOCK:
                tasks = load_gids()
                for gid, meta in list(tasks.items()):
                    if meta.get("status") in ("complete", "done", "failed", "error") or meta.get("error"):
                        removed.append(gid)
                        tasks.pop(gid, None)
                if removed:
                    save_gids(tasks)
            self._json({"ok": True, "count": len(removed)})
            return
        self.send_error(404)

    def _serve_index(self):
        try:
            body = open(INDEX_PATH, "rb").read()
        except Exception:
            body = b"<h1>ONEFILM - index.html not found</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    load_baidu()
    threading.Thread(target=watchdog, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
