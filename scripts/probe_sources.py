#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测各图源对原神女角色的覆盖量（只统计，不下载）。

数据源（已实测连通）：
  - yande.re   : 高质量原画 CDN，Danbooru 1.0 标签体系，有 rating:q/e
  - safebooru  : SFW 大库，标签带 _(genshin_impact) 后缀
  - xbooru     : NSFW 库
"""
import json, os, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(BASE), "metadata")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": url.split("/")[0] + "//" + url.split("/")[2] + "/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def n_yandere(tag, limit=100):
    try:
        d = get_json("https://yande.re/post.json?limit=%d&tags=%s" % (limit, urllib.parse.quote(tag)))
        return len(d)
    except Exception as e:
        return -1


def n_safebooru(tag, limit=100):
    try:
        d = get_json("https://safebooru.org/index.php?page=dapi&s=post&q=index&limit=%d&json=1&tags=%s"
                     % (limit, urllib.parse.quote(tag)))
        return len(d) if isinstance(d, list) else -1
    except Exception:
        return -1


def n_xbooru(tag, limit=100):
    try:
        d = get_json("https://xbooru.com/index.php?page=dapi&s=post&q=index&limit=%d&json=1&tags=%s"
                     % (limit, urllib.parse.quote(tag)))
        return len(d) if isinstance(d, list) else -1
    except Exception:
        return -1


def main():
    chars = json.load(open(os.path.join(BASE, "characters.json")))["characters"]
    todo = [c for c in chars if not c.get("skip")]
    print("探测 %d 个角色（已跳过 %d 个幼态角色）\n" % (len(todo), len(chars) - len(todo)), flush=True)

    rows = []
    for i, c in enumerate(todo, 1):
        y_all = n_yandere(c["id"]); time.sleep(1.1)
        y_exp = n_yandere(c["id"] + " rating:e"); time.sleep(1.1)
        sb = n_safebooru(c["sb"]); time.sleep(1.1)
        row = {"id": c["id"], "cn": c["cn"], "yandere": y_all, "yandere_explicit": y_exp, "safebooru": sb}
        rows.append(row)
        print("[%2d/%d] %-22s %-6s y=%3d e=%3d sb=%3d" % (i, len(todo), c["id"], c["cn"], y_all, y_exp, sb), flush=True)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "probe_result.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    ty = sum(r["yandere"] for r in rows if r["yandere"] > 0)
    te = sum(r["yandere_explicit"] for r in rows if r["yandere_explicit"] > 0)
    ts = sum(r["safebooru"] for r in rows if r["safebooru"] > 0)
    print("\n=== 汇总 ===")
    print("yande.re 合计 ≥ %d 张（其中 explicit ≥ %d）" % (ty, te))
    print("safebooru 合计 ≥ %d 张" % ts)
    top = sorted(rows, key=lambda r: -(r["yandere"] + r["safebooru"]))[:15]
    print("\n覆盖最多的角色:")
    for r in top:
        print("  %-22s y=%-3d sb=%-3d" % (r["id"], r["yandere"], r["safebooru"]))


if __name__ == "__main__":
    main()
