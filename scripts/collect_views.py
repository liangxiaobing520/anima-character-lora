#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视角定向补抓：按「角色 + 视角标签」组合查询，把训练集的视角分布配平。

为什么需要这个：
  原 collect.py 按"数量配额"抓图，抓到目标数就停。而 booru 默认按热度排序，
  热门图绝大多数是"正面大图/半身"，于是侧面、背面、全身这些姿势被挤掉。
  实测雷电将军训练集：上半身 15.9% vs 全身 6.2% —— 模型自然学会爱裁一半。

  本脚本反过来：先看缺哪个视角，再用 safebooru 的 AND 组合查询定向捞。
  （safebooru 的角色 tag 是裸名 raiden_shogun，不是 xxx_(genshin_impact)）

用法：
  python3 collect_views.py --char raiden_shogun \
      --views full_body:400 from_side:400 from_behind:300 --min-side 900
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect as C

SAFE = "https://safebooru.org/index.php?page=dapi&s=post&q=index"


def norm_safe(it):
    """转成 collect.py 统一的 post 结构"""
    return {"source": "safebooru", "sid": str(it.get("id")), "md5": it.get("hash", ""),
            "tags": it.get("tags", ""), "rating": "s", "w": it.get("width", 0),
            "h": it.get("height", 0), "url": it.get("file_url") or it.get("image", ""),
            "sample": it.get("sample_url", ""), "score": 0, "src_page": "", "filesize": 0}


def query_view(bare, view, pages, limit=100):
    """角色 + 视角 的 AND 组合查询"""
    out = []
    for p in range(pages):
        t = bare if not view else "%s %s" % (bare, view)
        url = "%s&limit=%d&pid=%d&json=1&tags=%s" % (SAFE, limit, p, urllib.parse.quote(t))
        try:
            d = C.http_json(url, referer="https://safebooru.org/")
        except Exception as e:
            C.log("   ! %s 第%d页失败: %s" % (view, p, str(e)[:80]))
            break
        if not isinstance(d, list) or not d:
            break
        out += [norm_safe(it) for it in d]
        C.log("   %s 第%d页 +%d 条 (累计 %d)" % (view, p, len(d), len(out)))
        if len(d) < limit:
            break
        time.sleep(1.1)
    return out


def count_have(meta_path, char, view):
    """从 posts.jsonl 统计该角色带某视角标签的已抓数量"""
    n = 0
    if not os.path.exists(meta_path):
        return 0
    for line in open(meta_path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("char_trigger") != char:
            continue
        if view in set((d.get("tags") or "").split()):
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", required=True, help="角色 id，如 raiden_shogun")
    ap.add_argument("--views", nargs="+", required=True,
                    help="视角:目标数，如 full_body:400 from_side:400 from_behind:300")
    ap.add_argument("--min-side", type=int, default=900, help="最短边下限")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--pages", type=int, default=12, help="每视角最多翻页(每页100)")
    args = ap.parse_args()

    chars = C.load_json(os.path.join(C.BASE, "characters.json"), {"characters": []})["characters"]
    c = next((x for x in chars if x["id"] == args.char), None)
    if not c:
        C.log("❌ 找不到角色 %s" % args.char)
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
    for spec in args.views:
        view, _, want = spec.partition(":")
        want = int(want or 200)
        cur = count_have(meta_path, bare, view)
        need = max(0, want - cur)
        C.log("\n=== %s：现有 %d → 目标 %d，需补 %d ===" % (view, cur, want, need))
        if need == 0:
            C.log("   已达标，跳过")
            continue

        cand = query_view(bare, view, args.pages)
        C.log("   共查询到 %d 条候选" % len(cand))
        picked, stat = [], {"dup": 0, "reject": 0, "noview": 0}
        for p in cand:
            # 必须真的带这个视角标签（AND 查询偶有偏差）
            if view not in C.post_tags(p):
                stat["noview"] += 1
                continue
            k = "%s:%s" % (p["source"], p["sid"])
            if k in keys or (p.get("md5") and p["md5"] in keys):
                stat["dup"] += 1
                continue
            ok, why, _pure = C.accept(p, args.min_side, bare)
            if not ok:
                stat["reject"] += 1
                continue
            keys.add(k)
            if p.get("md5"):
                keys.add(p["md5"])
            picked.append(p)
            if len(picked) >= need:
                break
        C.log("   去重过滤后选 %d 张 %s" % (len(picked), stat))
        if picked:
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                list(ex.map(lambda p: C.download_one(p, outdir, bare, meta_path), picked))
            C.log("   下载完成 %.0fs | 全局 ok=%d skip=%d fail=%d (%.1fMB)"
                  % (time.time() - t0, C._stat["ok"], C._stat["skip"], C._stat["fail"],
                     C._stat["bytes"] / 1e6))
            total += len(picked)
        seen[bare] = sorted(keys)
        C.save_json(seen_path, seen)

    n1 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("\n=== 完成：%s 从 %d 张 → %d 张（本次新增 %d）===" % (bare, n0, n1, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
