#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基元律动 (tokenrhythm.studio) 账号余额查询工具
================================================

用法：
    python jyld_balance.py                       # 交互输入凭据，查询后自动进入实时监控
    python jyld_balance.py "13800000000----sess_xxx----sk_tr_xxx----rf_tr_xxx----UUID"
    python jyld_balance.py --json "13800000000----sess_xxx----sk_tr_xxx----rf_tr_xxx----UUID"
    python jyld_balance.py -w --interval 60 "sess_xxx"   # 强制监控模式，60 秒刷新一次

选项：
    -w, --watch          强制进入实时监控模式（非交互/管道输出时也生效）
    -i, --interval N     刷新间隔秒数，默认 30
    --json               输出原始 JSON（查询一次后退出，不进入监控）

说明：
    交互模式下查询完成后自动进入实时监控：每 N 秒刷新余额/消费/调用数，
    余额变化会显示 Δ 增量。按 Q 或回车退出监控，Ctrl+C 强制退出。

支持两种输入：
  1) 整体粘贴 ---- 分隔的凭据串（推荐）：
     手机号----sess_xxx----sk_tr_xxx----rf_tr_xxx----UUID
  2) 交互逐项输入（只填 sess 也能查询，sk/rf 可选）

原理：sess_ 会话令牌作为 Authorization: Bearer 调用官方 API。
"""
import json
import sys
import urllib.error
import urllib.request

API_BASE = "https://tokenrhythm.studio/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 20

# ---------- 凭据解析 ----------

def parse_credential(raw):
    """解析 ---- 分隔的凭据串，或单段凭据。返回 dict。"""
    raw = (raw or "").strip()
    cred = {"phone": None, "sess": None, "sk": None, "rf": None, "uuid": None}
    if not raw:
        return cred
    parts = [p.strip() for p in raw.replace("|", "----").split("----") if p.strip()]
    if parts and not any(p.startswith(("sess_", "sk_", "rf_")) for p in parts):
        cred["phone"] = parts.pop(0)  # 第一段是手机号
    for p in parts:
        if p.startswith("sess_"):
            cred["sess"] = p
        elif p.startswith("sk_"):
            cred["sk"] = p
        elif p.startswith("rf_"):
            cred["rf"] = p
        elif len(p) == 36 and p.count("-") == 4:
            cred["uuid"] = p
    return cred


# ---------- API 调用 ----------

def api_get(path, bearer, timeout=TIMEOUT):
    req = urllib.request.Request(API_BASE + path)
    req.add_header("Authorization", "Bearer " + bearer)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        raise ApiError(e.code, body, path)


class ApiError(Exception):
    def __init__(self, status, body, path):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"HTTP {status} @ {path}: {body[:300]}")


# ---------- 输出 ----------

def fmt_cny(v):
    """把 '66.50609740' 格式化为 '66.50609740 (¥66.51)'"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{v}（¥{f:,.2f}）"


def print_user(data):
    print("\n【账号信息】")
    print(f"  用户ID   : {data.get('id')}")
    print(f"  用户名   : {data.get('name')}")
    print(f"  手机号   : {data.get('phoneMasked') or '-'}")
    print(f"  邮箱     : {data.get('emailMasked') or '-'}")
    print(f"  状态     : {data.get('status')}")
    print(f"  角色     : {data.get('role')}")
    print(f"  注册时间 : {data.get('joinedAt')}")


def print_wallet(w):
    print("\n【钱包余额】")
    rows = [
        ("可用余额", "availableBalanceCny"),
        ("  其中赠送", "giftAvailableCny"),
        ("  其中充值", "rechargeBalanceCny"),
        ("赠送总额", "giftTotalCny"),
        ("赠送冻结", "giftLockedCny"),
        ("冻结余额", "frozenBalanceCny"),
        ("欠费", "debtBalanceCny"),
        ("赠送状态", "giftStatus"),
    ]
    for label, key in rows:
        v = w.get(key)
        if v is None:
            continue
        if key == "giftStatus":
            print(f"  {label:<6}: {v}")
        else:
            print(f"  {label:<6}: {fmt_cny(v)}")
    print(f"  货币     : {w.get('currency')}")
    if w.get("asOf"):
        print(f"  数据时间 : {w['asOf']}")


def print_usage(u):
    print("\n【用量统计】")
    print(f"  调用次数   : {u.get('calls')} 次"
          f"（成功 {u.get('successCalls')} / 错误 {u.get('errorCalls')} / 中止 {u.get('abortedCalls')}）")
    print(f"  输入 tokens: {u.get('inputTokens'):,}")
    print(f"  输出 tokens: {u.get('outputTokens'):,}")
    print(f"  累计消费   : {fmt_cny(u.get('costCny'))}")
    print(f"  当前余额   : {fmt_cny(u.get('availableBalanceCny'))}")
    if u.get("expiringBalanceCny") is not None:
        print(f"  即将到期   : {fmt_cny(u.get('expiringBalanceCny'))}")
    if u.get("nextExpiryAt"):
        print(f"  到期时间   : {u['nextExpiryAt']}")
    reward = u.get("signupReward")
    if reward:
        print("  注册奖励   :")
        print(f"    策略     : {reward.get('policy')}")
        print(f"    总额     : {fmt_cny(reward.get('totalEligibleCny'))}")
        print(f"    已发放   : {fmt_cny(reward.get('grantedCny'))}")
        print(f"    状态     : {reward.get('status')}")
        if reward.get("activationRewardExpiresAt"):
            print(f"    发放到期 : {reward['activationRewardExpiresAt']}")


# ---------- 主流程 ----------

def query(bearer, as_json=False):
    """用 bearer 查询并打印结果。"""
    me = api_get("/auth/me", bearer)
    wallet = api_get("/wallet/summary", bearer)
    usage = api_get("/usage-summary", bearer)

    if as_json:
        print(json.dumps({"auth": me, "wallet": wallet, "usage": usage},
                         ensure_ascii=False, indent=2))
        return

    if me.get("code") != 0 or not me.get("data"):
        print(f"鉴权接口异常: {json.dumps(me, ensure_ascii=False)}")
        return
    print_user(me["data"])
    if wallet.get("code") == 0 and wallet.get("data"):
        print_wallet(wallet["data"])
    else:
        print("\n[钱包接口异常]", json.dumps(wallet, ensure_ascii=False))
    if usage.get("code") == 0 and usage.get("data"):
        print_usage(usage["data"])
    else:
        print("\n[用量接口异常]", json.dumps(usage, ensure_ascii=False))


# ---------- 实时监控 ----------

def refresh_line(bearer, last):
    """拉取一次最新余额/用量，与上次对比。返回 (成功?, 显示行文本)。"""
    import time
    ts = time.strftime("%H:%M:%S")
    try:
        wallet = api_get("/wallet/summary", bearer)
        usage = api_get("/usage-summary", bearer)
    except ApiError as e:
        return False, f"[{ts}] 刷新失败: {e.status} {e.body[:100]}"
    except Exception as e:
        return False, f"[{ts}] 刷新异常: {e}"

    if wallet.get("code") != 0 or not wallet.get("data"):
        return False, f"[{ts}] 钱包接口异常"
    if usage.get("code") != 0 or not usage.get("data"):
        return False, f"[{ts}] 用量接口异常"

    w, u = wallet["data"], usage["data"]
    try:
        bal = float(w.get("availableBalanceCny") or 0)
        cost = float(u.get("costCny") or 0)
        calls = u.get("calls") or 0
    except (TypeError, ValueError):
        return False, f"[{ts}] 数据格式异常"

    prev = last.get("bal")
    delta = (bal - prev) if prev is not None else None
    last.update(bal=bal, cost=cost, calls=calls)

    parts = [f"可用 {bal:,.2f}"]
    if delta is not None and abs(delta) >= 1e-8:
        parts.append(f"Δ{delta:+,.6f}")
    parts.append(f"已消费 {cost:,.2f}")
    parts.append(f"调用 {calls} 次")
    return True, f"[{ts}] " + " | ".join(parts)


def monitor_loop(bearer, interval):
    """定时刷新监控。按 Q/回车退出；无键盘可用时用 Ctrl+C 退出。"""
    import time
    try:
        import msvcrt  # Windows 键盘检测
        kb = True
    except ImportError:
        kb = False

    print("\n┌─ 实时监控模式 ─────────────────────────────────┐")
    print(f"│ 每 {interval} 秒刷新余额，按 Q 退出，Ctrl+C 强制退出 │")
    print("└─────────────────────────────────────────────────┘")
    last = {}
    next_at = 0.0
    while True:
        if kb and msvcrt.kbhit():
            key = msvcrt.getwch().lower()
            if key in ("q", "x", "\r", "\n", "\x1b"):
                print("\n已退出监控。")
                return
        now = time.time()
        if now >= next_at:
            next_at = now + interval
            ok, line = refresh_line(bearer, last)
            print(line)
        time.sleep(0.5)


def parse_args(argv):
    """解析命令行参数。返回 (as_json, watch, interval, rest)。"""
    as_json = "--json" in argv
    watch = "-w" in argv or "--watch" in argv
    interval = 30
    for i, a in enumerate(argv):
        if a in ("-i", "--interval") and i + 1 < len(argv):
            try:
                interval = max(1, int(argv[i + 1]))
            except ValueError:
                pass
    skip = {"--json", "--watch", "-w"}
    rest = [a for i, a in enumerate(argv) if a not in skip
            and not (a in ("-i", "--interval")
                     or (i > 0 and argv[i - 1] in ("-i", "--interval")))]
    return as_json, watch, interval, rest


def main():
    as_json, watch, interval, args = parse_args(sys.argv[1:])

    if args:
        raw = " ".join(args)
    else:
        print("基元律动余额查询工具")
        print("-" * 50)
        print("请粘贴凭据串（---- 分隔，顺序不限），例如：")
        print("  13800000000----sess_xxx----sk_tr_xxx----rf_tr_xxx----UUID")
        print("或直接粘贴 sess_xxx 一段。")
        print("-" * 50)
        raw = input("凭据: ").strip()

    cred = parse_credential(raw)
    if not cred["sess"] and not cred["sk"]:
        print("未识别到 sess_ 或 sk_ 令牌，请检查输入。")
        sys.exit(1)

    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    # 优先用 sess 会话令牌，失败再尝试 sk API Key
    tried = []
    for key in ("sess", "sk"):
        token = cred.get(key)
        if not token:
            continue
        tried.append(key)
        try:
            query(token, as_json=as_json)
            # 查询成功后：交互模式自动进入监控；--watch 强制进入
            if not as_json and (watch or interactive):
                monitor_loop(token, interval)
            print("\n查询完成 ✔")
            return
        except ApiError as e:
            print(f"[{key}] 查询失败: {e.status} {e.body[:200]}")
        except Exception as e:
            print(f"[{key}] 查询异常: {e}")

    print(f"\n所有令牌（{', '.join(tried)}）均无效。")
    print("提示: sess 会话可能已过期，可用 rf_ 刷新令牌换新会话，或重新登录获取。")
    sys.exit(1)


def pause_if_interactive():
    """交互终端下等待回车，避免双击运行时窗口闪退看不到结果。"""
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            input("\n按回车键退出...")
    except Exception:
        pass


if __name__ == "__main__":
    # Windows 控制台中文兼容 + 实时输出（监控模式需逐行 flush）
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    code = None
    try:
        code = main()
    except SystemExit as e:
        code = e.code
    except KeyboardInterrupt:
        print("\n已取消。")
        code = 1
    except Exception as e:
        print(f"\n[脚本异常] {e}")
        code = 1
    finally:
        # 双击运行时保持窗口，展示结果后再退出
        pause_if_interactive()
    sys.exit(0 if code is None else code)
