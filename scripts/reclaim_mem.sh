#!/usr/bin/env bash
# ============================================================
# 把 WSL 的 page cache 还给 Windows（vmmemWSL 瘦身）
#
# 为什么需要它：
#   WSL2 的 autoMemoryReclaim=gradual 只在「Linux 侧自己觉得内存有富余」时
#   才会把页还给 Windows。而训练/采集这类任务会大批量读文件，把 page cache
#   撑到几个 G —— Linux 视角看着"内存紧张"，回收就被卡住，vmmemWSL 长期
#   停在 6G 不降（实测 45 秒纹丝不动）。
#
#   手动 drop_caches 之后，Linux 侧 free 立刻涨起来，autoMemoryReclaim 随即
#   开始工作：实测 6011MB → 3711MB（40 秒），Windows 可用 2571MB → 5136MB。
#
# 为什么不用 sudo：
#   WSL 内 sudo 需要密码；改用 Windows 侧的 wsl.exe -u root 通道，等效提权，
#   且不影响当前这个 WSL 实例里跑着的其他进程（DSH 等）。
#
# 用法:
#   bash reclaim_mem.sh            # 清理并打印前后对比
#   bash reclaim_mem.sh --quiet    # 只清理
# ============================================================
set -u

WSL_EXE=/mnt/c/Windows/System32/wsl.exe
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

win_free() {
  $PS -NoProfile -Command "\$o=Get-CimInstance Win32_OperatingSystem; [math]::Round(\$o.FreePhysicalMemory/1KB)" 2>/dev/null \
    | tr -d '\r\n\000 '
}
vmmem() {
  $PS -NoProfile -Command "\$p=Get-Process vmmemWSL -ErrorAction SilentlyContinue; if(\$p){[math]::Round(\$p.WS/1MB)}else{'NA'}" 2>/dev/null \
    | tr -d '\r\n\000 '
}

if [ "$QUIET" -eq 0 ]; then
  echo "清理前: vmmemWSL=$(vmmem) MB | Windows 可用=$(win_free) MB"
fi

# 丢缓存（不动任何进程、不碰任何数据）
"$WSL_EXE" -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' >/dev/null 2>&1

if [ "$QUIET" -eq 0 ]; then
  echo "已清 page cache，等 autoMemoryReclaim 归还（20s）..."
  sleep 20
  echo "清理后: vmmemWSL=$(vmmem) MB | Windows 可用=$(win_free) MB"
  echo
  echo "WSL 内:"
  free -h | head -2
fi
