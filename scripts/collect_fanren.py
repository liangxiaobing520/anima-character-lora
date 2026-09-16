#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凡人修仙传角色图采集（360 图片搜索源，供 LoRA 训练）

为什么不用 booru：safebooru/danbooru 是日系图站，国漫零收录
（实测 a_record_of_a_mortals_journey_to_immortality = 0 张，donghua = 0 张）。
360 图片搜索的接口还能用（百度/搜狗已返回 Forbid spider access）。

接口: https://image.so.com/j?q=<keyword>&sn=<offset>&pn=<count>
返回: {"total": N, "list": [{"img": 原图URL, "thumb": 缩略图, "title":..., "width":..., "height":...}]}

产出目录: raw/<char_id>/  —— 与既有流程一致，之后跑 build_dataset.py
         即可硬链接进 train/by_character/<char_id>/ 用于训练。

用法:
  python3 collect_fanren.py --test                 # 只查不下载，看各角色素材量
  python3 collect_fanren.py --per-char 300         # 采到每角色 300 张
  python3 collect_fanren.py --only nangong_wan     # 只采一个角色
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
RAW = os.path.join(ROOT, "raw")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 凡人修仙传女性角色（id 用于目录名与 LoRA trigger，cn 用于搜索关键词）
FANREN = [
    ("nangong_wan",  "南宫婉"),    # 女主
    ("zi_ling",      "紫灵"),      # 女二
    ("yin_yue",      "银月"),
    ("dong_xuaner",  "董宣儿"),
    ("chen_qiaoqian", "陈巧倩"),
    ("mu_peiling",   "慕沛灵"),
    ("lin_yinping",  "林银屏"),
    ("mo_caihuan",   "墨彩环"),
    ("yuan_yao",     "元瑶"),
    ("yan_li",       "妍丽"),
    ("liu_lee",      "柳乐儿"),
    ("gan_jiuzhen",  "甘九真"),
    ("ling_yuling",  "凌玉灵"),   # 人界化神修士（2026-09-15 追加）
    ("yan_ruyan",    "燕如嫣"),   # 灵界（2026-09-15 追加）
]

SERIES_TAG = "fanren_xiuxian_zhuan"   # 作品 trigger，所有角色共用


def log(*a):
    print(*a, flush=True)


def search_360(keyword, sn=0, pn=30):
    """查 360 图片，返回 list[{img, thumb, title, w, h}]"""
    q = urllib.parse.quote(keyword)
    url = "https://image.so.com/j?q=%s&sn=%d&pn=%d" % (q, sn, pn)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://image.so.com/"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read())
    except Exception as e:
        log("   ⚠️ 搜索失败 sn=%d: %s" % (sn, e))
        return []
    out = []
    for it in d.get("list", []):
        u = it.get("img") or it.get("thumb")
        if not u:
            continue
        out.append({
            "url": u,
            "thumb": it.get("thumb", ""),
            "title": it.get("title", ""),
            "w": int(it.get("width") or 0),
            "h": int(it.get("height") or 0),
        })
    return out, int(d.get("total") or 0)


def count_of(keyword):
    r = search_360(keyword, 0, 1)
    return r[1] if isinstance(r, tuple) else 0


def download(item, outdir, char_id, cn, min_side, seen_md5):
    """下载单图 + 写 caption。返回 True/False"""
    url = item["url"]
    # 大图优先，失败再退回缩略图
    cands = [url] + ([item["thumb"]] if item.get("thumb") and item["thumb"] != url else [])
    data = None
    for u in cands:
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Referer": "https://image.so.com/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
            if len(b) > 2048:
                data = b
                break
        except Exception:
            continue
    if not data:
        return False

    md5 = hashlib.md5(data).hexdigest()
    if md5 in seen_md5:
        return False

    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        ext = ".jpg"
    name = "%s_%s%s" % (char_id, md5[:16], ext)
    dst = os.path.join(outdir, name)

    # 跨运行去重：同名文件已存在 = 这张图早前采过。
    # 360 对同一关键词的搜索结果有上限，重复采集只会把同样的图重下一遍
    # （实测 nangong_wan 日志写"138→274"，实际文件数仍是 138 —— 白耗带宽，
    # 还把"收 N 张"报成了增量）。真要重采请先删掉对应文件。
    if os.path.exists(dst):
        return False

    # 校验图片真实尺寸（360 给的 width/height 不可靠）
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if min(w, h) < min_side:
            return False
        if im.mode not in ("RGB", "L", "RGBA"):
            im = im.convert("RGB")
        im.save(dst)          # 顺便统一格式
    except Exception:
        # PIL 不可用就按原始字节存，尺寸过滤退回接口给的元数据
        if item["w"] and item["h"] and min(item["w"], item["h"]) < min_side:
            return False
        with open(dst, "wb") as f:
            f.write(data)

    # caption: 角色 trigger + 作品 trigger
    # 必须与图片同名(含 char_id 前缀)：build_dataset.py 按 <图基名>.txt 找 caption，
    # 少了前缀会让整批图片被当成"无 caption"跳过
    # (2026-09-15 踩坑：12 个凡人角色 train/by_character 全 0 张，就是这条引起的)
    cap = os.path.join(outdir, "%s_%s.txt" % (char_id, md5[:16]))
    with open(cap, "w", encoding="utf-8") as f:
        f.write("%s, %s, 1girl, solo\n" % (char_id, SERIES_TAG))
    seen_md5.add(md5)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-char", type=int, default=300, help="每个角色目标张数")
    ap.add_argument("--min-side", type=int, default=640, help="最短边下限(px)")
    ap.add_argument("--pages", type=int, default=12, help="最多翻几页(每页30条)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default="", help="只跑指定角色 id(逗号分隔)")
    ap.add_argument("--test", action="store_true", help="只查素材量不下载")
    args = ap.parse_args()

    want = {x.strip() for x in args.only.split(",") if x.strip()}
    chars = [c for c in FANREN if not want or c[0] in want]
    if not chars:
        log("❌ 没有匹配的角色(--only=%s)" % args.only)
        return 1

    log("凡人修仙传角色采集 | 360 图片源 | 目标 %d 张/角色 | 最短边 %d"
        % (args.per_char, args.min_side))

    if args.test:
        log("")
        log("%-16s %-10s %s" % ("id", "中文", "搜索命中"))
        for cid, cn in chars:
            kw = "凡人修仙传 %s 高清" % cn
            n = count_of(kw)
            log("%-16s %-10s %d" % (cid, cn, n))
            time.sleep(1.0)
        return 0

    grand_ok = 0
    for cid, cn in chars:
        outdir = os.path.join(RAW, cid)
        os.makedirs(outdir, exist_ok=True)
        have = len([f for f in os.listdir(outdir)
                    if f.lower().endswith((".jpg", ".png", ".webp", ".jpeg"))])
        if have >= args.per_char:
            log("\n=== %s(%s) 已有 %d 张,跳过 ===" % (cid, cn, have))
            continue

        log("\n=== %s(%s)  现有 %d,目标 %d ===" % (cid, cn, have, args.per_char))
        seen_md5 = set()
        got = 0
        # 两轮关键词回退：先"高清"（360 筛选过、成图率高但候选少），采不满再用裸
        # 关键词补。实测冷门角色裸词命中量能翻倍（凌玉灵 107→356、燕如嫣 84→223），
        # 混进来的小图由 --min-side 挡掉。
        for kw_pat in ("凡人修仙传 %s 高清", "凡人修仙传 %s"):
            if have + got >= args.per_char:
                break
            tag = "高清" if kw_pat.endswith("高清") else "裸词"
            for page in range(args.pages):
                if have + got >= args.per_char:
                    break
                kw = kw_pat % cn
                res = search_360(kw, sn=page * 30, pn=30)
                items = res[0] if isinstance(res, tuple) else []
                if not items:
                    log("   [%s] 第 %d 页无结果,换关键词" % (tag, page + 1))
                    break
                with ThreadPoolExecutor(max_workers=args.workers) as ex:
                    rs = list(ex.map(
                        lambda it: download(it, outdir, cid, cn, args.min_side, seen_md5),
                        items))
                ok = sum(1 for x in rs if x)
                got += ok
                log("   [%s] 第 %d 页: 候选 %d -> 收 %d (累计 %d)"
                    % (tag, page + 1, len(items), ok, have + got))
                time.sleep(1.2)

        log("   %s 完成: %d -> %d 张" % (cid, have, have + got))
        grand_ok += got

    log("\n=== 全部完成: 新增 %d 张 ===" % grand_ok)
    log("下一步: 把新角色加进 characters.json,再跑 build_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
