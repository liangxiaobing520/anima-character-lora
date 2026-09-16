"""生图负面词策略：底线锁死，画风可切。

- 固定底线 NEG_MINOR：child, kid, loli, shota, minor  —— 任何开关都关不掉
- 画风压制 NEG_STYLE：3d, cg, realistic              —— 默认开启，保持二次元画风

开启 3D / 写实画风的两种方式（任一即可）：
  1) 环境变量  ANIMA_ALLOW_3D=1    对所有引用本模块的脚本生效
  2) 命令行    --allow-3d           仅 studio_gen.py 支持（内部就是设上面那个环境变量）

用法：
    from neg_policy import NEG_MINOR, NEG_STYLE, neg_safety
    neg = NEG_QUALITY + neg_safety() + HAND_NEG

历史：2026-09-14 前 3d/cg/realistic 与未成年底线写死在同一个常量里（NEG_SAFETY），
用户要求解禁 3D/写实后拆成两段，底线保持不变、画风改为可切。
"""
import os

# 固定底线：绝对不可关闭
NEG_MINOR = "child, kid, loli, shota, minor, "
# 画风压制：默认开启
NEG_STYLE = "3d, cg, realistic, "

_TRUTHY = ("1", "true", "yes", "on", "y")

# 向后兼容：旧代码/旧脚本里仍写死 NEG_SAFETY 的地方拿到的是「默认压制」版本
NEG_SAFETY = NEG_MINOR + NEG_STYLE


def env_allow_3d():
    """环境变量 ANIMA_ALLOW_3D 是否为真（每次调用都重新读，便于运行时切换）"""
    return os.environ.get("ANIMA_ALLOW_3D", "").strip().lower() in _TRUTHY


def allow_3d():
    """当前是否放开 3D/写实"""
    return env_allow_3d()


def neg_style():
    """画风压制词；开关打开时返回空串"""
    return "" if allow_3d() else NEG_STYLE


def neg_safety():
    """底线 + 画风（画风受开关控制，底线永远在）"""
    return NEG_MINOR + neg_style()


def describe():
    """人类可读的当前状态，用于日志"""
    if allow_3d():
        return "画风：已放开 3D/写实（ANIMA_ALLOW_3D=%s）" % os.environ.get("ANIMA_ALLOW_3D")
    return "画风：默认压制 3D/写实（二次元）；加 --allow-3d 或 ANIMA_ALLOW_3D=1 可放开"
