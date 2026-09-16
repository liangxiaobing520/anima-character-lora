#!/usr/bin/env bash
# ============================================================
# 用"两轮关键词"新逻辑补采早期 12 个凡人角色。
#
# 背景：这些角色首轮采集时脚本只搜"凡人修仙传 <角色> 高清"，
#       而 360 上裸关键词（不加"高清"）的候选量常是前者的 2-3 倍
#       （实测凌玉灵 107→356、燕如嫣 84→223）。新逻辑第二轮回退到裸词，
#       能把漏掉的那批图捞回来。已有文件由 download() 的同名去重直接跳过，
#       所以重跑只补新的，不会重复下载。
#
# 用法: setsid nohup bash recollect_fanren.sh > /tmp/fanren_collect3.log 2>&1 < /dev/null &
# ============================================================
set -u
GD=/home/xiaozeng/lora_train/genshin_dataset

log() { echo "[$(date '+%T')] $*"; }

log "等待当前采集进程结束..."
while pgrep -f "[c]ollect_fanren" >/dev/null 2>&1; do sleep 10; done
log "采集已结束，开始补采 12 个角色（两轮关键词）"

cd "$GD" || exit 1
python3 scripts/collect_fanren.py --per-char 300 --min-side 640 \
  --only nangong_wan,zi_ling,yin_yue,dong_xuaner,chen_qiaoqian,mu_peiling,lin_yinping,mo_caihuan,yuan_yao,yan_li,liu_lee,gan_jiuzhen

log "补采完成"
