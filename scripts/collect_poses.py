#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姿势/动作定向补抓（含 NSFW 源）

背景：视角配平只解决了「正面/侧面/背面」，姿势维度仍是空白
      （跪 1.3% / 蹲 0.5% / 躺 2.4%）。本脚本按姿势 tag 定向补。

两个源：
  safebooru  直连、SFW、量大          —— 常规姿势（坐/躺/跪/蹲/跑/跳）
  xbooru     需走 socks5 代理、NSFW    —— 成人姿势与暴露内容

安全约束（硬性）：
  · 只处理成年角色（角色表里 adult=true）
  · 复用 collect.accept() 的过滤：命中 loli/child/shota/underage 等标签一律丢弃
  · 丢弃 comic/manga/monochrome（黑白漫画会污染画风）

用法：
  python3 collect_poses.py --char raiden_shogun \
      --sfw sitting:300 lying:200 kneeling:100 \
      --nsfw nude:200 sex:150
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect as C

PROXY = "socks5h://127.0.0.1:10810"
SAFE_API = "https://safebooru.org/index.php?page=dapi&s=post&q=index"
XBOORU_API = "https://xbooru.com/index.php?page=dapi&s=post&q=index"


def curl_json(url, use_proxy=False, timeout=30):
    """用 curl 拉 JSON（xbooru 必须走代理，urllib 不支持 socks5）"""
    cmd = ["curl", "-s", "-m", str(timeout)]
    if use_proxy:
        cmd += ["-x", PROXY]
    cmd += ["-H", "User-Agent: Mozilla/5.0", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except Exception as e:
        C.log("      ! 请求失败: %s" % str(e)[:70])
        return None


def norm_safe(it):
    return {"source": "safebooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
            "tags": it.get("tags", ""), "rating": "s", "w": it.get("width", 0),
            "h": it.get("height", 0), "url": it.get("file_url") or it.get("image", ""),
            "sample": it.get("sample_url", ""), "score": 0, "src_page": "", "filesize": 0}


def norm_xbooru(it):
    return {"source": "xbooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
            "tags": it.get("tags", ""), "rating": it.get("rating", ""),
            "w": int(it.get("width", 0) or 0), "h": int(it.get("height", 0) or 0),
            "url": it.get("file_url", ""), "sample": it.get("sample_url", ""),
            "score": int(it.get("score", 0) or 0), "src_page": it.get("source", ""),
            "filesize": int(it.get("file_size", 0) or 0)}


def query(api, bare, pose, pages, use_proxy, limit=100):
    """角色 + 姿势 的 AND 查询"""
    out = []
    for p in range(pages):
        t = bare if not pose else "%s %s" % (bare, pose)
        url = "%s&limit=%d&pid=%d&json=1&tags=%s" % (api, limit, p, urllib.parse.quote(t))
        d = curl_json(url, use_proxy=use_proxy)
        if not isinstance(d, list) or not d:
            break
        out += [norm_xbooru(x) if "xbooru" in api else norm_safe(x) for x in d]
        if len(d) < limit:
            break
        time.sleep(1.2)
    return out


def download_proxy(p, outdir, trigger, meta_path):
    """走代理下载（xbooru 用），其余逻辑复用 collect.download_one"""
    if p["source"] != "xbooru":
        return C.download_one(p, outdir, trigger, meta_path)
    dl = p.get("sample") or p.get("url")
    if not dl:
        return None
    ext = os.path.splitext(urllib.parse.urlparse(dl).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = "%s_%s%s" % (p["source"], p["sid"], ext)
    dst = os.path.join(outdir, name)
    cap = os.path.join(outdir, "%s_%s.txt" % (p["source"], p["sid"]))
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        return dst
    cmd = ["curl", "-s", "-m", "150", "-x", PROXY, "-o", dst, "-w", "%{http_code}", dl]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.stdout.strip() != "200" or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
            if os.path.exists(dst):
                os.remove(dst)
            with C._lock:
                C._stat["fail"] += 1
            return None
        with open(cap, "w", encoding="utf-8") as f:
            f.write(C.make_caption(p, trigger))
        C.append_jsonl(meta_path, dict(p, file=name, char_trigger=trigger,
                                       dl_kind="sample", dl_url=dl))
        with C._lock:
            C._stat["ok"] += 1
            C._stat["bytes"] += os.path.getsize(dst)
        return dst
    except Exception:
        with C._lock:
            C._stat["fail"] += 1
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", required=True)
    ap.add_argument("--sfw", nargs="*", default=[], help="safebooru 姿势:目标数")
    ap.add_argument("--nsfw", nargs="*", default=[], help="xbooru 姿势:目标数（走代理）")
    ap.add_argument("--min-side", type=int, default=640)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pages", type=int, default=10)
    args = ap.parse_args()

    chars = C.load_json(os.path.join(C.BASE, "characters.json"), {"characters": []})["characters"]
    c = next((x for x in chars if x["id"] == args.char), None)
    if not c:
        C.log("❌ 找不到角色 %s" % args.char)
        return 1
    if not c.get("adult"):
        C.log("❌ 角色 %s 非成年，拒绝抓取成人内容" % args.char)
        return 1

    bare = c["id"]
    outdir = os.path.join(C.RAW, bare)
    os.makedirs(outdir, exist_ok=True)
    seen_path = os.path.join(C.META, "seen_ids.json")
    meta_path = os.path.join(C.META, "posts.jsonl")
    seen = C.load_json(seen_path, {})
    keys = set(seen.get(bare, []))
    n0 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("角色 %s (%s) 现有 %d 张" % (bare, c["cn"], n0))

    total = 0
    plan = [(t, False) for t in args.sfw] + [(t, True) for t in args.nsfw]
    for spec, is_nsfw in plan:
        pose, _, want = spec.partition(":")
        want = int(want or 100)
        api = XBOORU_API if is_nsfw else SAFE_API
        tag_desc = "%s [%s]" % (pose, "xbooru/NSFW" if is_nsfw else "safebooru")
        C.log("\n=== %s  目标 %d 张 ===" % (tag_desc, want))

        cand = query(api, bare, pose, args.pages, use_proxy=is_nsfw)
        C.log("   查询到 %d 条候选" % len(cand))
        picked, stat = [], {"dup": 0, "reject": 0, "nopose": 0}
        for p in cand:
            if pose and pose not in C.post_tags(p):
                stat["nopose"] += 1
                continue
            k = "%s:%s" % (p["source"], p["sid"])
            if k in keys or (p.get("md5") and p["md5"] in keys):
                stat["dup"] += 1
                continue
            ok, why, _ = C.accept(p, args.min_side, bare)
            if not ok:
                stat["reject"] += 1
                continue
            keys.add(k)
            if p.get("md5"):
                keys.add(p["md5"])
            picked.append(p)
            if len(picked) >= want:
                break
        C.log("   去重过滤后选 %d 张 %s" % (len(picked), stat))
        if picked:
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                list(ex.map(lambda p: download_proxy(p, outdir, bare, meta_path), picked))
            C.log("   下载完成 %.0fs | ok=%d skip=%d fail=%d (%.1fMB)"
                  % (time.time() - t0, C._stat["ok"], C._stat["skip"], C._stat["fail"],
                     C._stat["bytes"] / 1e6))
            total += len(picked)
        seen[bare] = sorted(keys)
        C.save_json(seen_path, seen)

    n1 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("\n=== 完成：%s 从 %d → %d 张（本次新增 %d）===" % (bare, n0, n1, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
