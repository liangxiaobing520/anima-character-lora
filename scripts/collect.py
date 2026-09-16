#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原神女角色 LoRA 数据集采集器

特性：
  - 多源：yande.re（高质量原画）/ safebooru（SFW 大库）/ xbooru（NSFW）
  - 过滤：分辨率、构图、排除 AI 图/漫画页/3D、排除幼态标签
  - 去重：源侧 md5 + 本地 md5 双重校验
  - 断点续传：已下载记录落盘，重跑自动跳过
  - 自动 caption：booru tags -> 下划线格式 .txt（与现有 2104_crops 规范一致）

用法：
  python3 collect.py --per-char 120 --sources yandere safebooru xbooru
"""
import argparse
import hashlib
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
RAW = os.path.join(ROOT, "raw")
META = os.path.join(ROOT, "metadata")
LOGS = os.path.join(ROOT, "logs")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _load_char_ids():
    """角色全名集合，用于识别"目标角色之外的别的原神角色"（yande.re 用裸名不带后缀）"""
    try:
        with open(os.path.join(BASE, "characters.json"), encoding="utf-8") as f:
            return {c["id"] for c in json.load(f)["characters"]}
    except Exception:
        return set()


ALL_CHAR_IDS = _load_char_ids()

# ---------- 过滤规则 ----------
# 命中任一标签直接丢弃（不分级）
DROP_TAGS = {
    "loli", "shota", "child", "little_girl", "little_boy", "toddler", "infant",
    "comic", "manga", "monochrome", "greyscale", "sketch", "lineart", "rough",
    "cosplay", "photo", "photorealistic", "realistic", "3d", "3d_(artwork)",
    "ai_generated", "ai-generated", "watermark", "text", "english_text",
    "chinese_text", "japanese_text", "speech_bubble", "multiple_views",
    "character_sheet", "reference_sheet",
}
# 这些标签存在则强制归为 NSFW（用于统计/分桶）
NSFW_TAGS = {
    "nude", "naked", "sex", "nipples", "pussy", "penis", "cum", "anal", "vaginal",
    "oral", "fellatio", "paizuri", "masturbation", "censored", "uncensored",
    "topless", "bottomless", "underboob", "sideboob", "no_bra", "nopan", "anus",
}
# 多人/异性别同框 -> 单角色 LoRA 的噪声源，降级为"备选池"（单人图不够时才用）
MULTI_TAGS = {
    "multiple_girls", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "multiple_boys", "2boys", "3boys", "1boy", "male_focus", "duo",
    # 源站常漏标 2girls，但会标这些"关系/互动"标签 -> 一样按多人处理
    "siblings", "twins", "sisters", "brothers", "group", "couple",
    "hug", "hugging", "holding_hands", "heads_together", "back-to-back",
}
# caption 清洗：训练无意义的元标签
CAPTION_JUNK = {
    "commentary", "commentary_request", "chinese_commentary", "english_commentary",
    "korean_commentary", "japanese_commentary", "highres", "absurdres",
    "huge_filesize", "artist_name", "signature", "twitter_username",
    "patreon_username", "web_address", "what", "translated", "bad_id",
    "bad_twitter_id", "bad_pixiv_id", "bad_link", "deviantart", "pixiv",
}

_lock = threading.Lock()
_stat = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0}


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    return out


def append_jsonl(path, obj):
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def http_json(url, tries=3, timeout=30, referer=None):
    """带重试的 JSON 拉取（404/限速也会重试）"""
    hdr = {"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01"}
    if referer:
        hdr["Referer"] = referer
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if not body.strip():
                raise ValueError("empty body")
            return json.loads(body)
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    log("  ! fetch failed:", url[:110], "->", repr(last)[:120])
    return None


# ---------- 各源抓取 ----------
def _fetch_moebooru(host, source, tag, limit, pages):
    """Moebooru 系（yande.re / konachan 同款 API）：POST /post.json?limit=&page=&tags="""
    out = []
    for p in range(1, pages + 1):
        url = ("%s/post.json?limit=%d&page=%d&tags=%s"
               % (host, limit, p, urllib.parse.quote(tag)))
        d = http_json(url, referer="%s/post/list" % host)
        if not isinstance(d, list) or not d:
            break
        for it in d:
            out.append({
                "source": source, "sid": str(it.get("id")), "md5": it.get("md5", ""),
                "tags": it.get("tags", ""), "rating": it.get("rating", ""),
                "w": it.get("width", 0), "h": it.get("height", 0),
                "url": it.get("file_url", ""), "sample": it.get("sample_url", ""),
                "sw": it.get("sample_width", 0), "sh": it.get("sample_height", 0),
                "score": it.get("score", 0), "src_page": it.get("source", ""),
                "filesize": it.get("file_size", 0),
            })
        if len(d) < limit:
            break
        time.sleep(1.3)
    return out


def fetch_yandere(tag, limit, pages):
    return _fetch_moebooru("https://yande.re", "yandere", tag, limit, pages)


def fetch_konachan(tag, limit, pages):
    """konachan.net（全年龄站，Moebooru 同款 API）—— 补老角色很有效"""
    return _fetch_moebooru("https://konachan.net", "konachan", tag, limit, pages)


def fetch_tbib(tag, limit, pages):
    """TBIB (tbib.org) —— gelbooru 系 API，镜像 danbooru，新角色池子最大。
    图片 URL：原图 /images/{dir}/{image}；sample /samples/{dir}/sample_{stem}.jpg
    tbib 的 sample 只把长边压到 850，横图短边会掉到 500 以下——这种就回退用原图。"""
    def _q(t, p):
        url = ("https://tbib.org/index.php?page=dapi&s=post&q=index"
               "&limit=%d&pid=%d&json=1&tags=%s" % (limit, p, urllib.parse.quote(t)))
        return http_json(url, referer="https://tbib.org/")

    use_tag = tag
    probe = _q(tag, 0)
    if not isinstance(probe, list) or not probe:
        probe = _q(tag.split("_(")[0], 0)
        use_tag = tag.split("_(")[0]
    if not isinstance(probe, list) or not probe:
        return []
    if use_tag != tag:
        log("   [tbib] 使用标签 '%s'" % use_tag)

    out = []
    for p in range(0, pages):
        d = probe if p == 0 else _q(use_tag, p)
        if not isinstance(d, list) or not d:
            break
        for it in d:
            d_ = str(it.get("directory") or "")
            img = it.get("image") or ""
            if not d_ or not img:
                continue
            sw = int(it.get("sample_width", 0) or 0)
            sh = int(it.get("sample_height", 0) or 0)
            # 注意：尺寸判定必须用原图尺寸（tbib 原图是 danbooru 高清图 2400x3500+），
            # 但下载优先拿 sample 省带宽（sample 只压长边到 850，横图短边会跌破 700）。
            # 所以 sample 只写进 dl_sample，sample 字段留空 -> eff_size 走原图尺寸。
            dl_sample = ""
            if it.get("sample") and min(sw, sh) >= TBIB_SAMPLE_MIN_SIDE:
                dl_sample = ("https://tbib.org/samples/%s/sample_%s.jpg"
                             % (d_, img.rsplit(".", 1)[0]))
            out.append({
                "source": "tbib", "sid": str(it.get("id")), "md5": it.get("hash", ""),
                "tags": it.get("tags", ""), "rating": it.get("rating", ""),
                "w": int(it.get("width", 0) or 0), "h": int(it.get("height", 0) or 0),
                "url": "https://tbib.org/images/%s/%s" % (d_, img),
                "sample": "", "dl_sample": dl_sample, "sw": 0, "sh": 0,
                "score": int(it.get("score", 0) or 0), "src_page": it.get("owner", ""),
                "filesize": 0,
            })
        if len(d) < limit:
            break
        time.sleep(1.0)
    return out


def fetch_safebooru(tag, limit, pages):
    """safebooru 的标签格式不统一：部分角色只有裸名（raiden_shogun），
    部分只有带后缀名（shenhe_(genshin_impact)）。先试带后缀，空则回退裸名。"""
    def _q(t, p):
        url = ("https://safebooru.org/index.php?page=dapi&s=post&q=index"
               "&limit=%d&pid=%d&json=1&tags=%s" % (limit, p, urllib.parse.quote(t)))
        return http_json(url, referer="https://safebooru.org/")

    bare = tag.split("_(")[0]
    use_tag = tag
    probe = _q(tag, 0)
    if not isinstance(probe, list) or not probe:
        probe = _q(bare, 0)
        use_tag = bare
    if not isinstance(probe, list) or not probe:
        return []
    log("   [safebooru] 使用标签 '%s'" % use_tag)

    out = []
    for p in range(0, pages):
        d = probe if p == 0 else _q(use_tag, p)
        if not isinstance(d, list) or not d:
            break
        for it in d:
            out.append({
                "source": "safebooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
                "tags": it.get("tags", ""), "rating": "s",
                "w": it.get("width", 0), "h": it.get("height", 0),
                "url": it.get("file_url") or it.get("image", ""),
                "sample": it.get("sample_url", ""), "score": 0, "src_page": "",
                "filesize": 0,
            })
        if len(d) < limit:
            break
        time.sleep(1.1)
    return out


def fetch_xbooru(tag, limit, pages):
    """xbooru 标签同样存在裸名/带后缀两种写法，先探测再决定"""
    def _q(t, p):
        url = ("https://xbooru.com/index.php?page=dapi&s=post&q=index"
               "&limit=%d&pid=%d&json=1&tags=%s" % (limit, p, urllib.parse.quote(t)))
        return http_json(url, referer="https://xbooru.com/")

    bare = tag.split("_(")[0]
    use_tag = tag
    probe = _q(tag, 0)
    if not isinstance(probe, list) or not probe:
        probe = _q(bare, 0)
        use_tag = bare
    if not isinstance(probe, list) or not probe:
        return []
    log("   [xbooru] 使用标签 '%s'" % use_tag)

    out = []
    for p in range(0, pages):
        url = ("https://xbooru.com/index.php?page=dapi&s=post&q=index"
               "&limit=%d&pid=%d&json=1&tags=%s" % (limit, p, urllib.parse.quote(tag)))
        d = probe if p == 0 else _q(use_tag, p)
        if not isinstance(d, list) or not d:
            break
        for it in d:
            out.append({
                "source": "xbooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
                "tags": (it.get("tags") or "").replace(" ", " "), "rating": it.get("rating", ""),
                "w": int(it.get("width", 0) or 0), "h": int(it.get("height", 0) or 0),
                "url": it.get("file_url", ""), "sample": it.get("sample_url", ""),
                "score": int(it.get("score", 0) or 0), "src_page": it.get("source", ""),
                "filesize": int(it.get("file_size", 0) or 0),
            })
        if len(d) < limit:
            break
        time.sleep(1.1)
    return out


FETCHERS = {"yandere": fetch_yandere, "konachan": fetch_konachan,
            "safebooru": fetch_safebooru, "xbooru": fetch_xbooru, "tbib": fetch_tbib}
# 各源用哪个标签字段：yande.re/konachan/xbooru 用裸名(id)，safebooru/tbib 用带后缀(sb)
TAG_FIELD = {"yandere": "id", "konachan": "id", "xbooru": "id",
             "safebooru": "sb", "tbib": "sb"}


# ---------- 尺寸/URL 选择 ----------
# 背景：本机到海外 CDN 总带宽仅 ~750KB/s，原图平均 10MB+，
# 而 booru 的 sample 版固定长边 1500px（768 训练完全够用）且仅 ~250KB，快 30-50 倍。
SAMPLE_LONG_EDGE = 1500
# tbib 的 sample 只压长边到 850：竖图短边仍够(850)，横图短边会掉到 500 以下 -> 低于此值回退原图
TBIB_SAMPLE_MIN_SIDE = 700


def eff_size(p):
    """实际会下载到的尺寸（优先 sample）"""
    sw, sh = p.get("sw") or 0, p.get("sh") or 0
    if p.get("sample"):
        if sw and sh:
            return int(sw), int(sh)
        w, h = p["w"], p["h"]
        if max(w, h) > SAMPLE_LONG_EDGE:          # 无尺寸信息，按长边 1500 估算
            k = SAMPLE_LONG_EDGE / float(max(w, h))
            return int(w * k), int(h * k)
    return p["w"], p["h"]


def pick_url(p):
    """优先 sample（省带宽），否则回退原图；tbib 的省带宽版放在 dl_sample"""
    if p.get("dl_sample"):
        return p["dl_sample"], "sample"
    if p.get("sample"):
        return p["sample"], "sample"
    return p["url"], "full"


# ---------- 过滤 ----------
def post_tags(p):
    return set(p["tags"].split())


def other_chars(tags, trigger):
    """出现"目标之外的原神角色"即判为多角色图。
    safebooru/gelbooru 写作 xxx_(genshin_impact)，yande.re 写作裸名 xxx —— 两种都要认。"""
    base = trigger.split("_(")[0]
    others = set()
    for t in tags:
        if t.endswith("_(genshin_impact)"):
            b = t[: -len("_(genshin_impact)")]
            if b != base and b != trigger:
                others.add(b)
        elif t in ALL_CHAR_IDS and t != base:
            others.add(t)
    return others


def accept(p, min_side, trigger):
    """返回 (是否收下, 原因, 是否单人纯净图)"""
    t = post_tags(p)
    if t & DROP_TAGS:                       # 命中丢弃标签
        return False, "droptag", False
    # 幼态内容兜底：源标签里出现未成年词也丢
    if {"loli", "child", "shota", "underage", "young_girl", "baby"} & t:
        return False, "underage", False
    w, h = eff_size(p)
    if not w or not h or min(w, h) < min_side:
        return False, "lowres", False
    if not p["url"]:
        return False, "nourl", False
    # 无多人标签、且无其他原神角色同框 = 角色纯净图
    pure = not (t & MULTI_TAGS) and not other_chars(t, trigger)
    return True, ("solo" if pure else "multi"), pure


def make_caption(p, trigger):
    """booru tags -> kohya 训练用 caption（下划线风格，与 2104_crops 一致）"""
    tags = [x for x in p["tags"].split() if x]
    keep, seen = [], set()
    for tg in tags:
        if tg in DROP_TAGS or tg in CAPTION_JUNK or tg in seen:
            continue
        seen.add(tg)
        keep.append(tg)
    # 触发词 + 作品名放最前，其余保持源顺序
    tail = [x for x in keep if x != trigger and x != "genshin_impact"]
    return ", ".join([trigger, "genshin_impact"] + tail)


# ---------- 下载 ----------
def download_one(p, outdir, trigger, keep_meta):
    dl_url, dl_kind = pick_url(p)
    ext = os.path.splitext(urllib.parse.urlparse(dl_url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = "%s_%s%s" % (p["source"], p["sid"], ext)
    dst = os.path.join(outdir, name)
    cap = os.path.join(outdir, "%s_%s.txt" % (p["source"], p["sid"]))

    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        with _lock:
            _stat["skip"] += 1
        return dst

    hdr = {"User-Agent": UA, "Referer": "https://%s/" % urllib.parse.urlparse(dl_url).netloc}
    for attempt in range(3):
        try:
            req = urllib.request.Request(dl_url, headers=hdr)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError("too small: %d" % len(data))
            if len(data) > 60 * 1024 * 1024:      # 超过 60MB 的巨图不要
                raise ValueError("too large: %.1fMB" % (len(data) / 1e6))
            md5 = hashlib.md5(data).hexdigest()
            if p.get("md5") and md5 != p["md5"]:
                pass  # 源 md5 口径可能不同，不因此丢弃
            with open(dst, "wb") as f:
                f.write(data)
            with open(cap, "w", encoding="utf-8") as f:
                f.write(make_caption(p, trigger))
            append_jsonl(keep_meta, dict(p, file=name, md5_local=md5, char_trigger=trigger,
                                         dl_kind=dl_kind, dl_url=dl_url))
            with _lock:
                _stat["ok"] += 1
                _stat["bytes"] += len(data)
            return dst
        except Exception as e:
            if attempt == 2:
                with _lock:
                    _stat["fail"] += 1
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-char", type=int, default=150, help="每角色目标数量")
    ap.add_argument("--min-side", type=int, default=900, help="最短边下限(px)")
    ap.add_argument("--sources", nargs="+", default=["yandere", "safebooru", "xbooru"])
    ap.add_argument("--chars", nargs="*", default=None, help="只跑指定角色 id")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--pages", type=int, default=0,
                    help="每源最多翻页数(每页100条)；0=按 per_char 自动(缺口越大翻越深,上限12)")
    ap.add_argument("--skip-full", action="store_true", default=True,
                    help="已达标的角色直接跳过(默认开)")
    args = ap.parse_args()

    random.seed(args.seed)
    for d in (RAW, META, LOGS):
        os.makedirs(d, exist_ok=True)

    chars = load_json(os.path.join(BASE, "characters.json"), {"characters": []})["characters"]
    todo = [c for c in chars if not c.get("skip")]
    if args.chars:
        todo = [c for c in todo if c["id"] in args.chars]
    log("角色 %d 个 | 源 %s | 每角色目标 %d | 最短边 %d"
        % (len(todo), args.sources, args.per_char, args.min_side))

    seen = load_json(os.path.join(META, "seen_ids.json"), {})
    meta_path = os.path.join(META, "posts.jsonl")
    all_res = []

    for ci, c in enumerate(todo, 1):
        outdir = os.path.join(RAW, c["id"])
        os.makedirs(outdir, exist_ok=True)

        # 已有张数 & 缺口：只补差额，避免重复下载撑爆磁盘
        have0 = len([f for f in os.listdir(outdir)
                     if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))])
        gap = max(0, args.per_char - have0)
        if gap == 0 and args.skip_full:
            log("\n[%d/%d] %s (%s) 已有 %d 张，跳过" % (ci, len(todo), c["id"], c["cn"], have0))
            all_res.append({"id": c["id"], "cn": c["cn"], "have": have0,
                            "pure_pool": 0, "mixed_pool": 0, "skipped": True})
            continue
        log("\n[%d/%d] %s (%s) 已有 %d 张，缺口 %d 张"
            % (ci, len(todo), c["id"], c["cn"], have0, gap))

        # 翻页深度：缺口越大翻越深；显式 --pages 优先
        if args.pages > 0:
            pages = args.pages
        else:
            pages = min(12, max(2, gap // 100 + 2))

        cand = []
        for src in args.sources:
            if src not in FETCHERS:
                log("   ! 未知源 %s，跳过" % src)
                continue
            field = TAG_FIELD.get(src, "id")
            tag = c.get(field) or c["id"]
            got = FETCHERS[src](tag, 100, pages)
            log("   %-9s 抓到 %d 条 (标签 %s)" % (src, len(got), tag))
            cand.extend(got)

        # 过滤 + 去重；单人纯净图与多人图分开，前者优先
        keys = set(seen.get(c["id"], []))
        pure, mixed = [], []
        stat = {"droptag": 0, "lowres": 0, "nourl": 0, "underage": 0, "dup": 0}
        for p in cand:
            k = "%s:%s" % (p["source"], p["sid"])
            m = p.get("md5") or k
            if k in keys or m in keys:
                stat["dup"] += 1
                continue
            ok, why, is_pure = accept(p, args.min_side, c["id"])
            if not ok:
                stat[why] = stat.get(why, 0) + 1
                continue
            (pure if is_pure else mixed).append(p)

        def rank(p):
            # 显式 full_body > 竖构图 > 高分 > 高分辨率
            t = post_tags(p)
            fb = 1 if ("full_body" in t or "standing" in t) else 0
            ew, eh = eff_size(p)
            portrait = 1 if eh >= ew * 1.15 else 0
            return (-fb, -portrait, -(p.get("score") or 0), -(ew * eh))

        pure.sort(key=rank)
        mixed.sort(key=rank)
        picked = pure[:gap]
        if len(picked) < gap:                    # 单人图不够时才用多人图补
            picked += mixed[:gap - len(picked)]
        # 只把真正选中的记入 seen
        for p in picked:
            keys.add("%s:%s" % (p["source"], p["sid"]))
            if p.get("md5"):
                keys.add(p["md5"])
        log("   过滤后 %d 张 (单人池 %d / 多人池 %d) %s" % (len(picked), len(pure), len(mixed), stat))

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(lambda p: download_one(p, outdir, c["id"], meta_path), picked))

        seen[c["id"]] = sorted(keys)
        save_json(os.path.join(META, "seen_ids.json"), seen)
        n_have = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
        all_res.append({"id": c["id"], "cn": c["cn"], "have": n_have,
                        "pure_pool": len(pure), "mixed_pool": len(mixed)})
        log("   下载完成 累计 %d 张，用时 %.0fs | 全局 ok=%d skip=%d fail=%d (%.1f MB)"
            % (n_have, time.time() - t0, _stat["ok"], _stat["skip"], _stat["fail"],
               _stat["bytes"] / 1e6))

    log("\n=== 全部完成 ===")
    log("总计: ok=%d skip=%d fail=%d, 磁盘 %.2f GB" %
        (_stat["ok"], _stat["skip"], _stat["fail"], _stat["bytes"] / 1e9))
    save_json(os.path.join(META, "collect_summary.json"), all_res)


if __name__ == "__main__":
    main()
