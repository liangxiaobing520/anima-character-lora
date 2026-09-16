#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据集质检：分辨率/构图/去重/NSFW 比例/角色纯净度"""
import hashlib
import json
import os
import sys

from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
RAW = os.path.join(ROOT, "raw")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

NSFW_MARK = {
    "nude", "naked", "nipples", "pussy", "penis", "cum", "anal", "vaginal", "sex",
    "oral", "fellatio", "paizuri", "masturbation", "censored", "uncensored",
    "topless", "bottomless", "underboob", "sideboob", "no_bra", "nopan", "anus",
    "sex_toy", "bondage", "tentacles", "dildo", "vibrator",
}
MULTI_MARK = {
    "multiple_girls", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "multiple_boys", "2boys", "3boys", "1boy", "male_focus", "duo",
    "siblings", "twins", "sisters", "brothers", "group", "couple", "hug",
}


def img_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def main():
    rows = []
    hashes = Counter()          # 内容 md5 -> 出现次数（跨角色去重检查）
    hash_where = {}
    total_imgs = 0

    for char_id in sorted(os.listdir(RAW)):
        cdir = os.path.join(RAW, char_id)
        if not os.path.isdir(cdir):
            continue
        imgs = [f for f in os.listdir(cdir) if f.lower().endswith(IMG_EXT)]
        sides, portraits, nsfw, multi = [], 0, 0, 0
        for f in imgs:
            p = os.path.join(cdir, f)
            w, h = img_size(p)
            if not w:
                continue
            sides.append(min(w, h))
            if h >= w * 1.15:
                portraits += 1
            txt = os.path.join(cdir, os.path.splitext(f)[0] + ".txt")
            if os.path.exists(txt):
                tags = set(open(txt, encoding="utf-8").read().replace(",", " ").split())
                if tags & NSFW_MARK:
                    nsfw += 1
                if tags & MULTI_MARK:
                    multi += 1
            try:
                with open(p, "rb") as fh:
                    m = hashlib.md5(fh.read()).hexdigest()
                hashes[m] += 1
                hash_where.setdefault(m, []).append("%s/%s" % (char_id, f))
            except Exception:
                pass
        total_imgs += len(imgs)
        rows.append({
            "id": char_id, "n": len(imgs),
            "portrait_pct": round(100.0 * portraits / max(len(imgs), 1), 1),
            "min_side_avg": int(sum(sides) / max(len(sides), 1)),
            "min_side_min": min(sides) if sides else 0,
            "nsfw_pct": round(100.0 * nsfw / max(len(imgs), 1), 1),
            "multi": multi,
        })

    dup_groups = {m: c for m, c in hashes.items() if c > 1}
    dup_files = sum(c - 1 for c in dup_groups.values())

    print("%-22s %5s %8s %9s %8s %6s" % ("角色", "张数", "竖构图%", "最短边均值", "NSFW%", "多人"))
    print("-" * 68)
    for r in rows:
        print("%-22s %5d %7.1f%% %9d %7.1f%% %6d"
              % (r["id"], r["n"], r["portrait_pct"], r["min_side_avg"], r["nsfw_pct"], r["multi"]))
    print("-" * 68)
    print("角色 %d 个 | 图片 %d 张 | 竖构图占比 %.1f%% | 平均最短边 %d"
          % (len(rows), total_imgs,
             sum(r["portrait_pct"] for r in rows) / max(len(rows), 1),
             sum(r["min_side_avg"] for r in rows) // max(len(rows), 1)))
    print("跨角色重复：%d 组，冗余 %d 个文件" % (len(dup_groups), dup_files))
    if dup_groups:
        for m, c in list(dup_groups.items())[:5]:
            print("   x%d: %s" % (c, ", ".join(hash_where[m][:4])))

    with open(os.path.join(ROOT, "metadata", "qc_report.json"), "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "total": total_imgs,
                   "dup_groups": len(dup_groups), "dup_files": dup_files},
                  f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
