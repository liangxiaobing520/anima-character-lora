#!/usr/bin/env python3
"""重建 README 的「📦 模型下载」章节。

用法：
    python3 scripts/update_readme_models.py            # 写入 README.md
    python3 scripts/update_readme_models.py --dry-run  # 只打印不写

为什么要有这个脚本：
    模型清单是**手写**的，队列却一直在跑 —— 结果 README 停在「20 个角色」，
    实际早就有 60 个了，两边长期对不上。改成从 characters.json（id→中文名）
    和 output/（实际成品）现算，跑一次就同步一次。

分组、排序规则：
    · 《原神》/《凡人修仙传》两段，段内按角色 id 字母序（跟旧版一致）
    · 凡人角色集合不写死在这里，而是从 scripts/queue_start.sh 的 FANREN
      变量里读 —— 免得两处名单各说各话（2026-09-17 就因为名单不同步漏训过 15 个角色）
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

DRY = "--dry-run" in sys.argv
SUFFIX = "_anima_lora.safetensors"


def load_cn_names():
    """id -> 中文名，来自 characters.json"""
    with open("scripts/characters.json", encoding="utf-8") as f:
        data = json.load(f)
    return {c["id"]: c.get("cn", c["id"]) for c in data["characters"]}


def load_fanren_ids():
    """从 queue_start.sh 里读 FANREN 名单，保持单一事实来源"""
    with open("scripts/queue_start.sh", encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^FANREN="(.*?)"', src, re.S | re.M)
    if not m:
        raise SystemExit("❌ 在 queue_start.sh 里找不到 FANREN 变量")
    return set(m.group(1).split())


def build_section(cn, fanren):
    done = sorted(
        os.path.basename(p)[: -len(SUFFIX)]
        for p in os.listdir("output")
        if p.endswith(SUFFIX)
    )
    genshin = [c for c in done if c not in fanren]
    fanren_done = [c for c in done if c in fanren]

    missing = [c for c in done if c not in cn]
    if missing:
        print(f"⚠️  这些成品在 characters.json 里没有中文名，将退化成 id: {missing}")

    L = []
    L.append("## 📦 模型下载\n")
    L.append(
        f"**{len(done)} 个角色 LoRA**，每个约 **88 MB** —— "
        "`dim 32 / alpha 16 / 768px / bf16`。"
    )
    L.append(
        "全部在 [**Releases**](../../releases) 页面按角色下载"
        "（队列仍在训练，会继续追加）。\n"
    )
    L.append("| 角色 | ID | 文件 | 大小 |")
    L.append("|---|---|---|---|")
    for title, group in (("《原神》", genshin), ("《凡人修仙传》", fanren_done)):
        if not group:
            continue
        L.append(f"| **{title}** | | | |")
        for c in group:
            L.append(f"| {cn.get(c, c)} | `{c}` | `{c}{SUFFIX}` | 88 MB |")
    return "\n".join(L), len(genshin), len(fanren_done)


def main():
    cn = load_cn_names()
    fanren = load_fanren_ids()
    section, n_g, n_f = build_section(cn, fanren)

    with open("README.md", encoding="utf-8") as f:
        readme = f.read()

    pat = re.compile(r"## 📦 模型下载\n.*?(?=\n## 📁 目录结构)", re.S)
    if not pat.search(readme):
        raise SystemExit("❌ README 里找不到「📦 模型下载」到「📁 目录结构」这一段")

    new = pat.sub(section + "\n", readme)

    print(f"原神 {n_g} 个 + 凡人 {n_f} 个 = {n_g + n_f} 个角色")

    if DRY:
        print("\n--- 生成内容预览 ---")
        print(section[:600] + "\n...(略)")
        return

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(new)
    print("✅ README.md 已更新")


if __name__ == "__main__":
    main()
