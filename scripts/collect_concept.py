#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姿势/表情/动作/服装 通用 LoRA 数据集采集（去角色化）

和 collect_views / collect_poses 的区别：
  那两个是「为某个角色补素材」，本脚本是「为通用概念建数据集」——
  · 不限定角色，按姿势 tag 全站抓（随机 pid 采样，保证角色多样性）
  · caption 去掉所有角色名与作品名（去角色化），只留概念标签
  · 这样训出来的是"姿势概念"，不绑定任何角色，可叠加任意角色 LoRA

用法：
  python3 collect_concept.py --name poses --tags sitting:50 kneeling:50 ... --total 600
  python3 collect_concept.py --name expressions --tags smile:60 crying:60 ...
"""
import argparse
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys_path = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, sys_path)
import collect as C

BASE = C.BASE
SAFE = "https://safebooru.org/index.php?page=dapi&s=post&q=index"

# 概念数据集根目录
CONCEPT_ROOT = os.path.join(os.path.dirname(C.BASE), "concept_loras")

# 作品名（caption 里要剔除）
SERIES_HINT = re.compile(r"^[a-z0-9_'\-]+_\([a-z0-9_'\-]+\)$")


def is_character_tag(t):
    """形如 raiden_shogun_(genshin_impact) 的角色/作品标签"""
    if SERIES_HINT.match(t):
        return True
    if t.endswith("_(cosplay)") or t.endswith("_(artist)"):
        return True
    return False


def make_concept_caption(p):
    """去角色化 caption：只留概念标签"""
    tags = [x for x in p["tags"].split() if x]
    keep, seen = [], set()
    for tg in tags:
        if tg in C.DROP_TAGS or tg in C.CAPTION_JUNK or tg in seen:
            continue
        if is_character_tag(tg):        # 去掉角色名/作品名
            continue
        seen.add(tg)
        keep.append(tg)
    return ", ".join(keep)


def norm(it):
    return {"source": "safebooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
            "tags": it.get("tags", ""), "rating": "s", "w": it.get("width", 0),
            "h": it.get("height", 0), "url": it.get("file_url") or it.get("image", ""),
            "sample": it.get("sample_url", ""), "score": 0, "src_page": "", "filesize": 0}


def query(tag, pages, limit=100, rand=False):
    """按 tag 查询；rand=True 时随机页码采样（避免只抓到最新/最热）"""
    out = []
    pids = [random.randint(0, 200) for _ in range(pages)] if rand else list(range(pages))
    for pid in pids:
        url = "%s&limit=%d&pid=%d&json=1&tags=%s" % (SAFE, limit, pid,
                                                      urllib.parse.quote(tag + " 1girl solo"))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                       "Referer": "https://safebooru.org/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
        except Exception:
            continue
        if not isinstance(d, list) or not d:
            continue
        out += [norm(x) for x in d]
        time.sleep(0.9)
    return out


def download(p, outdir, meta_path):
    """复用 collect.download_one 但用去角色化 caption"""
    dl = p.get("sample") or p.get("url")
    if not dl:
        return None
    ext = os.path.splitext(urllib.parse.urlparse(dl).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = "safebooru_%s%s" % (p["sid"], ext)
    dst = os.path.join(outdir, name)
    cap = os.path.join(outdir, "safebooru_%s.txt" % p["sid"])
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        return dst
    for attempt in range(3):
        try:
            req = urllib.request.Request(dl, headers={
                "User-Agent": "Mozilla/5.0", "Referer": "https://safebooru.org/"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError("small")
            with open(dst, "wb") as f:
                f.write(data)
            with open(cap, "w", encoding="utf-8") as f:
                f.write(make_concept_caption(p))
            C.append_jsonl(meta_path, dict(p, file=name, concept=os.path.basename(outdir)))
            with C._lock:
                C._stat["ok"] += 1
                C._stat["bytes"] += len(data)
            return dst
        except Exception:
            if attempt == 2:
                with C._lock:
                    C._stat["fail"] += 1
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="概念集名，如 poses / expressions")
    ap.add_argument("--tags", nargs="+", required=True, help="tag:目标数，如 sitting:50 kneeling:50")
    ap.add_argument("--min-side", type=int, default=640)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", type=int, default=3)
    args = ap.parse_args()

    outdir = os.path.join(CONCEPT_ROOT, args.name)
    os.makedirs(outdir, exist_ok=True)
    meta_path = os.path.join(CONCEPT_ROOT, "%s.jsonl" % args.name)
    seen_path = os.path.join(CONCEPT_ROOT, "%s_seen.json" % args.name)
    seen = C.load_json(seen_path, {})
    keys = set(seen.get("ids", []))

    n0 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("概念集 [%s] 现有 %d 张，目标 tags: %s" % (args.name, n0, args.tags))

    total = 0
    for spec in args.tags:
        tag, _, want = spec.partition(":")
        want = int(want or 50)
        C.log("\n=== %s  目标 %d ===" % (tag, want))
        cand = query(tag, args.pages, rand=True)
        C.log("   候选 %d 条" % len(cand))
        picked, stat = [], {"dup": 0, "reject": 0, "notag": 0}
        for p in cand:
            if tag not in C.post_tags(p):
                stat["notag"] += 1
                continue
            k = "%s:%s" % (p["source"], p["sid"])
            if k in keys or (p.get("md5") and p["md5"] in keys):
                stat["dup"] += 1
                continue
            ok, why, _ = C.accept(p, args.min_side, "1girl")   # 用通用 trigger 判多角色
            if not ok:
                stat["reject"] += 1
                continue
            keys.add(k)
            if p.get("md5"):
                keys.add(p["md5"])
            picked.append(p)
            if len(picked) >= want:
                break
        C.log("   采用 %d 张 %s" % (len(picked), stat))
        if picked:
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                list(ex.map(lambda p: download(p, outdir, meta_path), picked))
            C.log("   下载 %.0fs | ok=%d fail=%d (%.1fMB)"
                  % (time.time() - t0, C._stat["ok"], C._stat["fail"], C._stat["bytes"] / 1e6))
            total += len(picked)
        seen["ids"] = sorted(keys)
        C.save_json(seen_path, seen)

    n1 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("\n=== 完成：[%s] %d -> %d 张（新增 %d）===" % (args.name, n0, n1, total))
    C.log("   目录: %s" % outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
