#!/usr/bin/env bash
# ============================================================
# 训练期间的内存守护 —— 定期把 page cache 还给 Windows
#
# 为什么需要它（2026-09-15 事故）：
#   train_batch.sh 只在每轮训练"结束之后"调用 reclaim_mem.sh，
#   但训练中途要读几百张图，buff/cache 会涨到 3~5G。WSL 只有 8G，
#   实测把训练进程和看门狗一起 OOM 掉了（yae_miko 跑到 127/1000 猝死）。
#   这个守护在训练进行期间每隔 INTERVAL 秒回收一次，堵住中途那段空窗。
#
# 用法: setsid nohup bash mem_guard.sh > /dev/null 2>&1 < /dev/null &
# ============================================================
set -u
INTERVAL=${INTERVAL:-180}
SELF_DIR=$(cd "$(dirname "$0")" && pwd)

while true; do
  sleep "$INTERVAL"
  # 只在真的有训练在跑时才回收，避免空转唤醒磁盘
  if ps -eo args 2>/dev/null | grep -q "[a]nima_train_network"; then
    bash "$SELF_DIR/reclaim_mem.sh" --quiet >/dev/null 2>&1
  fi
done
