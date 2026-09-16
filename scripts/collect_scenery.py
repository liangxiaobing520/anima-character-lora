#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""古风场景 LoRA 数据集采集（纯场景 / no_humans）

与 collect_concept.py(姿势集)的区别：
  · 查询用「<tag> no_humans」——只要画面里没人的图，
    否则模型会把「人」一起学进场景概念，叠加角色 LoRA 时会打架
  · caption 额外剔除人物相关 tag(发色/瞳色/服装/表情/姿势/构图视角)，
    只留建筑、地形、天象、植被、天气这类真正的场景标签
  · tag 里的 "+" 统一换成空格再 quote，避免 %2B 被 booru 误解析

用法：
  python3 collect_scenery.py --name guofeng \\
      --tags mountain+scenery:200 waterfall+scenery:120 bridge+scenery:120 \\
             castle+scenery:110 torii+scenery:100 shrine+scenery:90 \\
             bamboo+scenery:90 temple+scenery:80 pagoda+scenery:55 \\
             lotus+scenery:35 moon+scenery:100 \\
      --min-side 640 --pages 4
"""
import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect as C
from collect_concept import is_character_tag, norm, CONCEPT_ROOT

SAFE = "https://safebooru.org/index.php?page=dapi&s=post&q=index"

# 人物相关 tag：场景数据集里必须剔除，否则模型会学"人"
HUMAN_TAGS = set("""
1girl 2girls 3girls 4girls 5girls 6+girls multiple_girls 1boy 2boys multiple_boys solo solo_focus
person people male female androgynous
long_hair short_hair very_long_hair twintails ponytail blonde_hair black_hair brown_hair blue_hair
red_hair white_hair pink_hair purple_hair green_hair silver_hair grey_hair orange_hair
two-tone_hair gradient_hair ahoge bangs hair_between_eyes hair_ornament hair_ribbon
breasts large_breasts huge_breasts small_breasts medium_breasts flat_chest nipples
cleavage underboob sideboob navel
eyes blue_eyes red_eyes green_eyes brown_eyes purple_eyes yellow_eyes golden_eyes grey_eyes black_eyes
looking_at_viewer looking_away looking_back looking_up looking_down looking_to_the_side
smile open_mouth closed_mouth blush expressionless grin frown parted_lips teeth tongue
skirt shirt dress uniform kimono school_uniform gloves boots hat thighhighs
standing sitting walking running lying on_back kneeling all_fours
from_side from_behind from_above from_below cowboy_shot portrait upper_body
""".split())


def make_scenery_caption(p):
    """场景 caption：剔除人物 tag + 角色/作品 tag，只留场景标签"""
    tags = [x for x in p["tags"].split() if x]
    keep, seen = [], set()
    for tg in tags:
        if tg in C.DROP_TAGS or tg in C.CAPTION_JUNK or tg in seen:
            continue
        if tg in HUMAN_TAGS:          # 人物相关
            continue
        if is_character_tag(tg):      # 角色名/作品名
            continue
        seen.add(tg)
        keep.append(tg)
    return ", ".join(keep)


def count_of(q):
    """查 tag 总数（safebooru XML 接口的 count 属性）。

    必要性：随机 pid 采样必须先知道池子有多少页。场景 tag 的池子通常只有
    几百到几千张（= 几页到几十页），若无脑 randint(0,150) 绝大多数页码都
    越界返回空——collect_concept 没暴露这问题是因为姿势 tag 动辄几万张。
    """
    url = "%s&limit=0&tags=%s" % (SAFE, urllib.parse.quote(q))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://safebooru.org/"})
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(512).decode("utf-8", "ignore")
        m = re.search(r'count="(\d+)"', head)
        return int(m.group(1)) if m else 0
    except Exception as e:
        C.log("   ⚠️ count 查询失败: %s" % e)
        return 0


def query_scenery(tag, pages, limit=100, rand=True):
    """按「<tag> no_humans」查询；按池子总数动态决定可用页码"""
    out = []
    q = (tag.replace("+", " ") + " no_humans").strip()
    total = count_of(q)
    pages_avail = max(1, min((total + limit - 1) // limit, 60))
    C.log("   池子 %d 张 / 可用页码 0..%d" % (total, pages_avail - 1))
    if total == 0:
        return out
    if rand:
        pids = random.sample(range(pages_avail), min(pages, pages_avail))
    else:
        pids = list(range(min(pages, pages_avail)))
    for pid in pids:
        url = "%s&limit=%d&pid=%d&json=1&tags=%s" % (
            SAFE, limit, pid, urllib.parse.quote(q))
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Referer": "https://safebooru.org/"})
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
    """下载 + 写场景 caption（不用 collect_concept 的人物版 caption）"""
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
                f.write(make_scenery_caption(p))
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
    ap.add_argument("--name", required=True, help="概念集名，如 guofeng")
    ap.add_argument("--tags", nargs="+", required=True,
                    help="tag:目标数，tag 可含 + 表示组合，如 mountain+scenery:200")
    ap.add_argument("--min-side", type=int, default=640)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="只查询不下载，看候选量")
    args = ap.parse_args()

    outdir = os.path.join(CONCEPT_ROOT, args.name)
    os.makedirs(outdir, exist_ok=True)
    meta_path = os.path.join(CONCEPT_ROOT, "%s.jsonl" % args.name)
    seen_path = os.path.join(CONCEPT_ROOT, "%s_seen.json" % args.name)
    seen = C.load_json(seen_path, {})
    keys = set(seen.get("ids", []))

    n0 = len([f for f in os.listdir(outdir) if not f.endswith(".txt")])
    C.log("场景集 [%s] 现有 %d 张，目标 %d 类" % (args.name, n0, len(args.tags)))

    total = 0
    for spec in args.tags:
        tag, _, want = spec.partition(":")
        want = int(want or 50)
        C.log("\n=== %s  目标 %d ===" % (tag, want))
        cand = query_scenery(tag, args.pages)
        C.log("   候选 %d 条" % len(cand))
        picked, stat = [], {"dup": 0, "reject": 0, "nohuman": 0, "small": 0}
        for p in cand:
            if "no_humans" not in C.post_tags(p):
                stat["nohuman"] += 1
                continue
            w, h = int(p.get("w") or 0), int(p.get("h") or 0)
            if min(w, h) < args.min_side:
                stat["small"] += 1
                continue
            k = "%s:%s" % (p["source"], p["sid"])
            if k in keys or (p.get("md5") and p["md5"] in keys):
                stat["dup"] += 1
                continue
            keys.add(k)
            if p.get("md5"):
                keys.add(p["md5"])
            picked.append(p)
            if len(picked) >= want:
                break
        C.log("   采用 %d 张 %s" % (len(picked), stat))
        if picked and not args.dry_run:
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
