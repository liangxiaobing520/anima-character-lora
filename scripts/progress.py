#!/usr/bin/env python3
"""数据集进度一览：每角色已抓张数 / 缺口 / 是否达标"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW  = os.path.join(ROOT, "raw")
EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 300

chars = json.load(open(os.path.join(ROOT, "scripts", "characters.json"),
                       encoding="utf-8"))["characters"]
todo = [c for c in chars if not c.get("skip")]

rows, done_n, total_n, gap_n = [], 0, 0, 0
for c in sorted(todo, key=lambda x: x["id"]):
    d = os.path.join(RAW, c["id"])
    n = len([f for f in os.listdir(d) if f.lower().endswith(EXTS)]) if os.path.isdir(d) else 0
    total_n += n
    rows.append((c["id"], c["cn"], n, max(0, TARGET - n)))
    if n >= TARGET: done_n += 1
    else: gap_n += TARGET - n

print(f"目标 {TARGET} 张/角色 | 角色 {len(todo)} 个 | 已达标 {done_n} | 总计 {total_n} 张 | 缺口 {gap_n} 张")
print("-" * 48)
for cid, cn, n, g in rows:
    flag = "✅" if g == 0 else ("🟡" if n >= TARGET * 0.7 else "🔴")
    print(f"{flag} {cid:<20} {cn:<8} {n:>4} 张   缺 {g}" if g else f"{flag} {cid:<20} {cn:<8} {n:>4} 张")
