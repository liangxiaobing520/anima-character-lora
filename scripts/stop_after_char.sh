#!/usr/bin/env bash
# ============================================================
# 等指定角色训完，自动停掉 lora-queue
#
# 为什么需要它：
#   队列跑完一个角色会**立刻**接着下一个 —— DONE 到下一个 `TRAIN 开始`
#   中间只有约 33~45 秒（build_dataset + 停 ComfyUI + 缓存 latent）。
#   用户说"XX 跑完就暂停"时靠人守着，很容易慢一步，白杀掉下一个角色的
#   一段时间（2026-09-17 beidou→navia 那回就多杀了 15 秒）。
#   轮询 5 秒 + 那个 30 秒的 build 窗口 ⇒ 通常在对方还没开训时就停住了。
#
# 用法（交给 systemd 托管，DSH 重启也带不走它）：
#   cd /home/xiaozeng/lora_train/genshin_dataset
#   systemd-run --user --unit=stop-after-<char> --collect \
#     --setenv=CHAR=<char> \
#     --property=StandardOutput=append:$PWD/logs/stop-after-<char>.log \
#     --property=StandardError=append:$PWD/logs/stop-after-<char>.log \
#     bash scripts/stop_after_char.sh
#
# 查：systemctl --user status stop-after-<char>
#     tail logs/stop-after-<char>.log
# 取消：systemctl --user stop stop-after-<char>
# ============================================================
set -u
GD=/home/xiaozeng/lora_train/genshin_dataset
CHAR="${CHAR:-}"
if [ -z "$CHAR" ]; then
  echo "用法: CHAR=<角色id> bash $0"
  exit 2
fi

DONE="$GD/batch_state/$CHAR.done"
echo "[$(date '+%F %T')] 守护启动：等 $CHAR 训完（目标 $DONE）"

# 1440 × 5s = 2 小时；800 步约 35 分钟，余量充足
for _ in $(seq 1 1440); do
  if [ -f "$DONE" ]; then
    sleep 4                       # 给队列留出写 .done、软链 LoRA 的收尾时间
    if systemctl --user stop lora-queue 2>/dev/null; then
      echo "[$(date '+%F %T')] $CHAR 已完成 → 已停 lora-queue ✅"
    else
      # 兜底：本脚本跑在 systemd --user 下，万一连不上 user bus（DBUS 环境缺失），
      # systemctl 会失败 —— 那就直接按 PID 杀，绝不能让队列继续往下跑。
      # 注：pattern 用 [t] 方括号，避免 grep 命中自己这条命令行。
      echo "[$(date '+%F %T')] $CHAR 已完成，但 systemctl 失败 → 兜底：直接杀进程"
      ps -eo pid,args | grep "[t]rain_batch\.sh"     | awk '{print $1}' | xargs -r kill
      ps -eo pid,args | grep "[a]nima_train_network" | awk '{print $1}' | xargs -r kill
      echo "[$(date '+%F %T')] 兜底杀进程已执行"
    fi
    exit 0
  fi
  sleep 5
done
echo "[$(date '+%F %T')] 超时 2 小时仍未等到 $CHAR.done，未执行停止"
exit 1
