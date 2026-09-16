#!/usr/bin/env bash
# ============================================================
# 训练僵死看门狗（独立于队列运行，不修改队列本身）
#
# 背景 2026-09-14 夜班事故：
#   furina@768 训练跑到 886/1000 步后僵死 —— 进程还在、显存占着 6.9G、
#   GPU 利用率 0%、日志 9.5 小时没动静；而队列的「等 GPU 空闲」只检测
#   进程是否存在，于是从 00:38 空等到 07:03（23100 秒），一个角色没训完。
#
# 本脚本专治这种「僵尸训练」：进程活着但日志长时间不推进 -> 判定僵死 -> 清理掉，
# 让队列的等待循环自然退出、继续下一个角色。
#
# 用法:
#   setsid nohup bash train_watchdog.sh > /dev/null 2>&1 < /dev/null &
# ============================================================
set -u

LOG=/tmp/train_watchdog.log
GD=/home/xiaozeng/lora_train/genshin_dataset
STALL_SEC=${STALL_SEC:-600}   # 日志超过这么久没更新 -> 判定僵死
CHECK=${CHECK:-60}            # 检查间隔

say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 取所有训练日志里最新的 mtime（训练进度用 \r 刷新，正常每几秒就写一次）
latest_log_mtime() {
  local m=0 f t
  for f in "$GD"/logs/train_*.log /tmp/train_batch.log; do
    [ -f "$f" ] || continue
    t=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    [ "$t" -gt "$m" ] && m=$t
  done
  echo "$m"
}

say "看门狗启动 | 僵死阈值 ${STALL_SEC}s | 检查间隔 ${CHECK}s"
STALLED_BEFORE=0

while true; do
  sleep "$CHECK"

  pid=$(pgrep -f "[a]nima_train_network\.py" | head -1)
  if [ -z "$pid" ]; then
    STALLED_BEFORE=0
    continue                      # 没有训练在跑，不关我事
  fi

  m=$(latest_log_mtime)
  if [ "$m" -eq 0 ]; then continue; fi
  age=$(( $(date +%s) - m ))

  if [ "$age" -ge "$STALL_SEC" ]; then
    util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader | tr -d ' %')
    mem=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader)
    if [ "$STALLED_BEFORE" -eq 0 ]; then
      say "!! 疑似僵死: pid=$pid 日志 ${age}s 未更新 | GPU util=${util}% mem=${mem}"
    fi
    STALLED_BEFORE=1
    # 连续两轮都判定僵死才动手，避免误杀「加载模型/缓存 latents」这类慢阶段
    if [ "$STALLED_BEFORE" -ge 2 ]; then
      say "!! 确认僵死 -> 清理 pid=$pid 及其 worker"
      pkill -9 -f "[a]nima_train_network\.py"
      sleep 3
      if pgrep -f "[a]nima_train_network\.py" >/dev/null; then
        say "   仍有残留进程"
      else
        say "   已清空，等队列的等待循环自行退出并继续"
      fi
      STALLED_BEFORE=0
    fi
  else
    STALLED_BEFORE=0
  fi
done
