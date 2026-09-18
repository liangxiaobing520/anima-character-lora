#!/usr/bin/env bash
# ============================================================
# 队列启动器 v1（2026-09-16）
#
# 为什么单独写这个：
#   ① WSL 一重启，nohup 队列照样全死 —— 日志原来写 /tmp/q2.log，
#      而 /tmp 是 tmpfs，重启即空，事后完全查不到进度到哪了。
#      现在日志固定落 $GD/logs/queue-<ts>.log（持久盘）。
#   ② 49 个角色的完整名单原来硬编码在 fanren_queue_switch.sh 里，
#      那个脚本是"切换器"，一次性用完就废；这里做成可重复调用的入口。
#   ③ train_batch.sh 自带断点续跑（batch_state/<char>.done 自动 SKIP），
#      所以本脚本幂等：重复执行只是把没训完的接着训。
#
# 用法:
#   bash scripts/queue_start.sh              # 跑完整名单（凡人 14 + 原神剩余）
#   bash scripts/queue_start.sh zi_ling      # 只跑指定角色
# ============================================================
set -u
GD=/home/xiaozeng/lora_train/genshin_dataset
mkdir -p "$GD/logs"

# 完整名单：凡人修仙传 14 女角优先，其后是原神剩余
# ⚠️ lin_yinping（林银屏）暂时移出：360 图源只收到 13 张，训不出可用 LoRA。
#    等换关键词补采到位再从下面加回来。其余小样本角色（柳乐儿/甘九真/燕如嫣/颜丽）
#    走 train_lora.sh 的"小样本自动降步数"（<60 张→300 步，<120 张→500 步）。
FANREN="nangong_wan zi_ling yin_yue dong_xuaner chen_qiaoqian mu_peiling \
mo_caihuan yuan_yao yan_li liu_lee gan_jiuzhen \
ling_yuling yan_ruyan"

# ⚠️ 这份名单必须跟 raw/ 里实际到位的角色同步，否则新采的角色会被**静默漏掉**
#    （2026-09-17 实测：名单只覆盖 15 个待训，实际有 30 个 —— 不带参数起队列会漏训一半）
GENSHIN="furina hu_tao yae_miko kamisato_ayaka mona keqing arlecchino shenhe \
eula fischl sangonomiya_kokomi barbara jean lynette yoimiya xiangling \
ningguang citlali noelle kujou_sara navia clorinde yelan faruzan \
sucrose rosaria beidou chiori yun_jin mavuika lisa signora mualani \
kuki_shinobu charlotte \
chasca candace dehya escoffier layla lumine nilou skirk varesa xilonen \
xianyun yanfei emilie lan_yan iansan"

if [ -n "${1:-}" ]; then
  CHARS="$*"
  TAG="manual"
else
  CHARS="$FANREN $GENSHIN"
  TAG="full"
fi

# ---------- 防重入：已有队列在跑就不要再起一个 ----------
# 两个 train_batch.sh 会在角色间隙的 60s 轮询里同时通过 GPU 检查 → 抢显存 OOM
if systemctl --user is-active --quiet lora-queue 2>/dev/null; then
  echo "❌ 已有队列在跑（systemd unit: lora-queue）。停掉：systemctl --user stop lora-queue"
  exit 1
fi
if pgrep -f "[t]rain_batch\.sh" >/dev/null 2>&1; then
  echo "❌ 检测到裸进程队列（非 systemd 托管）：$(ps -eo pid,args | grep '[t]rain_batch.sh' | grep -v grep | awk '{print $1}' | tr '\n' ' ')"
  echo "   先 kill 掉再启，否则会双队列抢显存"
  exit 1
fi

TS=$(date +%Y%m%d-%H%M%S)
LOG="$GD/logs/queue-$TS-$TAG.log"

# ---------- 交给 systemd --user 托管，彻底脱离 DSH/tmux 进程树 ----------
# 2026-09-16 连续栽了两次，都是"重启连带杀后台任务"：
#   ① WSL 整体重启 → 所有 Linux 进程无条件消失；
#   ② `dsh-web-restart.sh` 末行的 `tmux kill-session -t dsh` → 连 `setsid nohup`
#      起的队列一起被带走（DSH 重启 = 重启 DSH 不等于重启 WSL，但照样杀干净）。
# 交给 systemd user manager 之后，DSH 怎么重启都动不了队列。
#
# 管理命令：
#   systemctl --user status lora-queue     # 状态
#   systemctl --user stop  lora-queue      # 停
#   journalctl --user -u lora-queue -f     # 实时输出（日志同时落下面的文件）
systemctl --user reset-failed lora-queue 2>/dev/null || true

systemd-run --user --unit=lora-queue --collect \
  --working-directory="$GD" \
  --setenv=TARGET_IMG=1 \
  --property=StandardOutput=append:"$LOG" \
  --property=StandardError=append:"$LOG" \
  bash scripts/train_batch.sh $CHARS

sleep 4
total=$(echo $CHARS | wc -w)
if systemctl --user is-active --quiet lora-queue; then
  echo "✅ 启动完成：队列由 systemd 托管（unit: lora-queue）· 共 $total 个角色（已完成的自动 SKIP）"
else
  echo "❌ 启动失败，查：systemctl --user status lora-queue"
  exit 1
fi
echo "日志：$LOG"
echo "查看进度：lora_train_status   或   tail -f $LOG"
