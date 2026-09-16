#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把《凡人修仙传》女角色注册进 characters.json。

背景：build_dataset.py / progress.py 会读 characters.json 取中文名(cn_map)，
      不注册的话报表里只有英文 id。
注意：sb 字段留空 —— 这批角色不走 booru 采集(国漫零收录)，素材来自
      collect_fanren.py(360 图片源)，用 train_batch.sh 时须配 TARGET_IMG=1
      跳过 collect.py 的扩采步骤。

用法: python3 add_fanren_to_characters.py [--dry]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CJ = os.path.join(BASE, "characters.json")

SERIES = "fanren_xiuxian_zhuan"

FANREN = [
    ("nangong_wan",   "南宫婉"),
    ("zi_ling",       "紫灵"),
    ("yin_yue",       "银月"),
    ("dong_xuaner",   "董宣儿"),
    ("chen_qiaoqian", "陈巧倩"),
    ("mu_peiling",    "慕沛灵"),
    ("lin_yinping",   "林银屏"),
    ("mo_caihuan",    "墨彩环"),
    ("yuan_yao",      "元瑶"),
    ("yan_li",        "妍丽"),
    ("liu_lee",       "柳乐儿"),
    ("gan_jiuzhen",   "甘九真"),
    ("ling_yuling",   "凌玉灵"),
    ("yan_ruyan",     "燕如嫣"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    with open(CJ, encoding="utf-8") as f:
        data = json.load(f)

    have = {c["id"] for c in data["characters"]}
    added = []
    for cid, cn in FANREN:
        if cid in have:
            continue
        data["characters"].append({
            "id": cid,
            "cn": cn,
            "sb": "",                      # 无 booru tag：不走 collect.py
            "adult": True,
            "skip": False,
            "series": SERIES,
        })
        added.append(cid)

    print("原有 %d 个角色，新增 %d 个：%s"
          % (len(have), len(added), ", ".join(added) or "无"))
    if args.dry:
        print("(--dry，未写盘)")
        return 0
    if not added:
        print("无需改动")
        return 0

    bak = CJ + ".bak-fanren-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(CJ, bak)
    print("备份 ->", os.path.basename(bak))

    # 原子写：队列可能正在读这个文件，必须先写临时文件再 replace
    d = os.path.dirname(CJ)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CJ)
    except Exception:
        os.path.exists(tmp) and os.remove(tmp)
        raise
    print("已写入 %s（共 %d 个角色）" % (os.path.basename(CJ), len(data["characters"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
