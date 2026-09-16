#!/usr/bin/env bash
# ============================================================
# 队列切换器 v2：把《凡人修仙传》女角色插到训练队首
#
# v1 实际踩到的两个坑（2026-09-15）：
#   ① 脚本名 recollect_fanren.sh 里含 "collect_fanren" 子串，
#      于是 `pgrep -f "[c]ollect_fanren"` 匹配到了脚本自己 → 死等自己结束，
#      白卡 1.5 小时。现在一律用 "[c]ollect_fanren\.py" 锚定 python 进程。
#   ② 采集一结束就切换会打断正在训练的角色。现在多等一个"训练间隙"
#      （无 anima_train_network 进程）——那一刻队列正好在 build 下一个角色，
#      kill 下去零浪费。
#
# 用法: setsid nohup bash fanren_queue_switch.sh > /tmp/fanren_switch.log 2>&1 < /dev/null &
# ============================================================
set -u
GD=/home/xiaozeng/lora_train/genshin_dataset

log() { echo "[$(date '+%T')] $*"; }

log "切换器 v2 启动"

# ---------- 1) 等素材补采结束 ----------
while pgrep -f "[c]ollect_fanren\.py" >/dev/null 2>&1; do sleep 10; done
log "采集已结束"

# ---------- 2) 等一个训练间隙 ----------
while pgrep -f "[a]nima_train_network\.py" >/dev/null 2>&1; do sleep 5; done
log "检测到训练间隙，立即切换"

# ---------- 3) 停旧队列 ----------
sleep 2
ps -eo pid,args | grep "[t]rain_batch.sh" | awk '{print $1}' | xargs -r kill 2>/dev/null
sleep 3
ps -eo pid,args | grep "[t]rain_batch.sh" | awk '{print $1}' | xargs -r kill -9 2>/dev/null
n_left=$(ps -eo args | grep -c "[t]rain_batch.sh")
log "旧队列已停 (残留 $n_left)"

# ---------- 4) 起新队列 ----------
# TARGET_IMG=1：跳过 collect.py 扩采（凡人素材走 360 源，booru 对国漫零收录；
#   原神角色素材也都已达标）。已完成的角色有 .done 标记，自动 SKIP。
cd "$GD" || exit 1
TARGET_IMG=1 setsid nohup bash scripts/train_batch.sh \
  nangong_wan zi_ling yin_yue dong_xuaner chen_qiaoqian mu_peiling \
  lin_yinping mo_caihuan yuan_yao yan_li liu_lee gan_jiuzhen \
  ling_yuling yan_ruyan \
  furina hu_tao yae_miko kamisato_ayaka mona keqing arlecchino shenhe \
  eula fischl sangonomiya_kokomi barbara jean lynette yoimiya xiangling \
  ningguang citlali noelle kujou_sara navia clorinde yelan faruzan \
  sucrose rosaria beidou chiori yun_jin mavuika lisa signora mualani \
  kuki_shinobu charlotte \
  > /tmp/q2.log 2>&1 < /dev/null &
sleep 3
log "新队列已启动（凡人 14 优先 + 原神剩余）→ /tmp/q2.log"
log "切换器退出"
