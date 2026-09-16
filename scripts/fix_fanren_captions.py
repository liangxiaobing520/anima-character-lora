#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 collect_fanren.py 早期版本留下的 caption 命名错位。

旧版把 caption 写成 <md5>.txt，而图片是 <char_id>_<md5>.<ext>，
build_dataset.py 按 <图基名>.txt 找 caption → 找不到 → 整批图片被跳过。
本脚本把 <md5>.txt 重命名为 <char_id>_<md5>.txt（只处理能配对到图片的）。

用法:
  python3 fix_fanren_captions.py --dry     # 只看要改多少，不动文件
  python3 fix_fanren_captions.py           # 实际重命名
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
RAW = os.path.join(ROOT, "raw")

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

# 与 collect_fanren.py 的 FANREN 保持一致
FANREN_IDS = [
    "nangong_wan", "zi_ling", "yin_yue", "dong_xuaner", "chen_qiaoqian",
    "mu_peiling", "lin_yinping", "mo_caihuan", "yuan_yao", "yan_li",
    "liu_lee", "gan_jiuzhen",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只报告不修改")
    ap.add_argument("--only", default="", help="只处理指定角色 id")
    args = ap.parse_args()

    ids = [c for c in FANREN_IDS if not args.only or c == args.only]
    grand = 0
    for cid in ids:
        d = os.path.join(RAW, cid)
        if not os.path.isdir(d):
            print("%-16s 目录不存在,跳过" % cid)
            continue
        files = set(os.listdir(d))
        renamed = 0
        already = 0
        orphans = 0
        for f in list(files):
            if not f.lower().endswith(".txt"):
                continue
            base = f[:-4]
            if base.startswith(cid + "_"):
                already += 1
                continue
            # 找同目录下同基名的图片
            img_hit = next(
                ("%s_%s%s" % (cid, base, e) for e in EXTS
                 if "%s_%s%s" % (cid, base, e) in files), None)
            if not img_hit:
                orphans += 1
                continue
            if not args.dry:
                os.rename(os.path.join(d, f),
                          os.path.join(d, "%s_%s.txt" % (cid, base)))
            renamed += 1
        grand += renamed
        print("%-16s 重命名 %4d | 已正确 %4d | 无对应图片 %4d"
              % (cid, renamed, already, orphans))

    print()
    print("%s %d 个 caption" % ("将重命名" if args.dry else "已重命名", grand))
    if args.dry:
        print("去掉 --dry 实际执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
