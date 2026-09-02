#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基元律动 (tokenrhythm.studio) 余额查询 —— Textual TUI 仪表盘
=============================================================

用法：
    python jyld_tui.py                                # 启动后在首屏粘贴凭据串
    python jyld_tui.py "手机号----sess_xxx----sk_tr_xxx"   # 直接传凭据
    python jyld_tui.py --interval 60 "sess_xxx"        # 指定默认刷新间隔(秒)

交互（三态焦点，↑↓ 切换层）：
    容器层  ←/→ 切换 sess 容器；Enter 进入该容器按钮层
    按钮层  ←/→ 在「删除 / 前移 / 高级状态」间移动；Enter 执行
    输入层  底部输入框粘贴凭据，Enter 添加新 sess
    ↑/↓    在 容器 / 按钮 / 输入 三态间升降

其它：R 立即刷新；=/- 调整刷新间隔；? 快捷键；Q/Ctrl+C 退出。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Static

from jyld_balance import (
    API_BASE,
    ApiError,
    api_get,
    fmt_cny,
    parse_credential,
)

EMPTY = "(无数据)"
DEFAULT_INTERVAL = 30
MIN_INTERVAL = 1
MAX_INTERVAL = 600

# 多 key 持久化文件（放项目目录，已被 .gitignore 排除）
STORAGE = Path(__file__).resolve().parent / "creds.json"


def _os_clipboard_text():
    """读取 Windows 系统剪贴板文本（ctypes）。非 Windows / 无文本返回 None。
    解决 conhost 下 Textual 依赖 OSC52 读不到系统剪贴板的问题。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        CF_UNICODETEXT = 13
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.OpenClipboard(0):
            return None
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            ptr = k32.GlobalLock(h)
            if not ptr:
                return None
            try:
                size = k32.GlobalSize(h)
                if size <= 0:
                    return None
                buf = ctypes.create_string_buffer(size)
                ctypes.memmove(buf, ptr, size)
                return buf.raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return None


class PasteInput(Input):
    """Input：Ctrl+V 时优先读 Windows 系统剪贴板（conhost 下 OSC52 不可用）。"""

    def action_paste(self) -> None:
        text = _os_clipboard_text() or self.app.clipboard
        if not text:
            return
        start, end = self.selection
        self.replace(text, start, end)

# 容器焦点层：容器 / 按钮 / 输入
LAYER_CONTAINER = "container"
LAYER_BUTTON = "button"
LAYER_INPUT = "input"


def load_keys():
    try:
        data = json.loads(STORAGE.read_text("utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("raw")]
    except Exception:
        pass
    return []


def save_keys(keys):
    try:
        STORAGE.write_text(json.dumps(keys, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def key_name(raw, idx):
    """为 sess 生成显示名：
    1) 有手机号等可读段 → 用它；2) 否则用 sess 令牌前缀；3) 再回退 账号#N。"""
    segs = [s.strip() for s in str(raw).replace("|", "----").split("----") if s.strip()]
    # 优先手机号等非令牌段
    for seg in segs:
        if seg.startswith(("sess_", "sk_", "rf_")):
            continue
        if len(seg) == 36 and seg.count("-") == 4:
            continue
        return seg[:18]
    # 否则用 sess 前缀，保证不同 sess 名字可区分
    for seg in segs:
        if seg.startswith("sess_"):
            return seg[:20]
    return f"账号{idx + 1}"


class SessPanel(Vertical):
    """一个 sess 容器（可承接焦点，供容器层方向键导航）。"""
    can_focus = True


def _cny_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _status_txt(status):
    if not status:
        return f"[dim]{EMPTY}[/]"
    low = str(status).lower()
    if low in ("active", "正常", "enabled"):
        return f"[bold #2ee6a8]● {status}[/]"
    if low in ("inactive", "disabled", "冻结", "禁用"):
        return f"[bold #ffd700]● {status}[/]"
    return f"[bold #ff5555]● {status}[/]"


def _basic_fields(data):
    """容器默认显示的基础字段：用户名/手机号/状态/可用余额/赠送。"""
    me = (data or {}).get("me") or {}
    d = data or {}
    md = me.get("data") or {}
    wd = (d.get("wallet") or {}).get("data") or {}
    lines = []
    lines.append(f"  [dim]用户名[/dim]  : {md.get('name') or EMPTY}")
    lines.append(f"  [dim]手机号[/dim]  : {md.get('phoneMasked') or EMPTY}")
    lines.append(f"  [dim]状态[/dim]    : {_status_txt(md.get('status'))}")
    avail = wd.get("availableBalanceCny")
    if avail is not None:
        an = _cny_num(avail)
        if an is not None:
            lines.append("  [dim]可用余额[/dim]")
            lines.append(f"  [bold #00ff9f]{an:,.6f}[/] [dim]¥[/]")
        else:
            lines.append(f"  [dim]可用余额[/dim]  : {avail}")
    else:
        lines.append("  [dim]可用余额[/dim]  : [dim]加载中…[/]")
    gift = wd.get("giftAvailableCny")
    lines.append(f"  [dim]赠送[/dim]    : {fmt_cny(gift) if gift is not None else '[dim]加载中…[/]'}")
    return "\n".join(lines)


def _advanced_fields(data):
    """「高级状态」展开后额外显示的字段。"""
    d = data or {}
    me = d.get("me") or {}
    md = me.get("data") or {}
    wd = (d.get("wallet") or {}).get("data") or {}
    ud = (d.get("usage") or {}).get("data") or {}
    lines = []
    lines.append(f"  [dim]用户ID[/dim]  : {md.get('id') or EMPTY}")
    lines.append(f"  [dim]邮箱[/dim]    : {md.get('emailMasked') or EMPTY}")
    lines.append(f"  [dim]角色[/dim]    : {md.get('role') or EMPTY}")
    lines.append(f"  [dim]注册时间[/dim]: {md.get('joinedAt') or EMPTY}")
    if wd.get("rechargeBalanceCny") is not None:
        lines.append(f"  [dim]充值[/dim]    : [magenta]{fmt_cny(wd['rechargeBalanceCny'])}[/]")
    if wd.get("giftTotalCny") is not None:
        lines.append(f"  [dim]赠送总额[/dim]: {fmt_cny(wd['giftTotalCny'])}")
    for label, keycolor in [
        ("赠送冻结", "giftLockedCny"),
        ("冻结余额", "frozenBalanceCny"),
        ("欠费", "debtBalanceCny"),
    ]:
        v = wd.get(keycolor)
        if v is None:
            continue
        n = _cny_num(v)
        if keycolor == "debtBalanceCny" and n and n > 0:
            lines.append(f"  [dim]欠费[/dim]    : [bold #ff5555]⚠ {fmt_cny(v)}[/]")
        else:
            lines.append(f"  [dim]{label}[/dim]    : [dim]{fmt_cny(v)}[/]")
    if wd.get("currency"):
        lines.append(f"  [dim]货币[/dim]    : {wd['currency']}")
    if wd.get("asOf"):
        # 只取日期时间部分，避免过长
        lines.append(f"  [dim]数据时间[/dim]: [silver]{wd['asOf']}[/]")

    if ud:
        err = ud.get("errorCalls") or 0
        if ud.get("calls") is not None:
            if err > 0:
                lines.append(f"  [dim]调用[/dim]    : [bold #ff5555]{ud.get('calls')}[/]（成功 [green]{ud.get('successCalls')}[/] / 错误 {err}）")
            else:
                lines.append(f"  [dim]调用[/dim]    : [bold #bb9af7]{ud.get('calls')}[/]")
        if ud.get("inputTokens") is not None:
            lines.append(f"  [dim]输入tokens[/dim]: {ud['inputTokens']:,}")
        if ud.get("outputTokens") is not None:
            lines.append(f"  [dim]输出tokens[/dim]: {ud['outputTokens']:,}")
        lines.append(f"  [dim]累计消费[/dim]: [bold #ffd700]{fmt_cny(ud.get('costCny'))}[/]")
        exp = ud.get("expiringBalanceCny")
        if exp is not None:
            n = _cny_num(exp)
            if n and n > 0:
                lines.append(f"  [dim]即将到期[/dim]: [bold #ff9e64]⚠ {fmt_cny(exp)}[/]")
            else:
                lines.append(f"  [dim]即将到期[/dim]: {fmt_cny(exp)}")
        if ud.get("nextExpiryAt"):
            lines.append(f"  [dim]到期时间[/dim]: [silver]{ud['nextExpiryAt']}[/]")
        reward = ud.get("signupReward")
        if reward:
            lines.append(f"  [dim]注册奖励[/dim]: 总额 {fmt_cny(reward.get('totalEligibleCny'))}"
                         f" / 已发 {fmt_cny(reward.get('grantedCny'))}"
                         f" / {reward.get('status') or '-'}")
    return "\n".join(lines)


class BallanceTUI(App):
    """多 sess 余额监控仪表盘。"""

    BINDINGS = [
        Binding("up", "layer_up", "上一层", show=False),
        Binding("down", "layer_down", "下一层", show=False),
        Binding("left", "nav_left", "左", show=False),
        Binding("right", "nav_right", "右", show=False),
        Binding("enter", "activate", "确认", show=False),
        Binding("ctrl+v", "paste_into_input", "粘贴", show=False),
        Binding("r", "refresh_now", "刷新"),
        Binding("=", "faster", "加快"),
        Binding("-", "slower", "放慢"),
        Binding("?", "toggle_help", "快捷键"),
        Binding("q", "quit", "退出"),
    ]
    CSS = """
    Screen { background: #0d1117; }
    #main {
        layout: horizontal;
        height: 1fr;
        padding: 1;
        overflow-x: auto;
        overflow-y: hidden;
    }
    #cred-screen {
        height: 100%;
        align: center middle;
        content-align: center middle;
    }
    #cred-input { width: 92; margin-top: 1; }
    SessPanel {
        border: round #7aa2f7;
        padding: 1 2;
        height: 100%;
        min-width: 30;
        max-width: 40;
        margin: 0 1 0 0;
        overflow-y: auto;
    }
    SessPanel.active {
        border: round #2ee6a8;
        border-title-color: #2ee6a8;
    }
    SessPanel .ops {
        width: 100%;
        margin-top: 1;
    }
    SessPanel .op-btn {
        height: 1;
        min-width: 8;
        margin: 0 1 0 0;
        border: none;
        background: #21262d;
        color: #c9d1d9;
    }
    SessPanel .op-btn.focused {
        background: #7aa2f7;
        color: #0d1117;
        text-style: bold;
    }
    #empty-hint {
        height: 100%;
        align: center middle;
        content-align: center middle;
        color: #6e7681;
    }
    #keybar {
        dock: bottom;
        height: auto;
        padding: 1 1 1 1;
        background: #161b22;
    }
    #keybar.hidden { display: none; }
    #keybar-top {
        height: 1;
        margin: 0 0 1 0;
    }
    #layer-badge {
        width: auto;
        min-width: 7;
        margin: 0 1 0 0;
        text-style: bold;
    }
    #layer-badge.container { color: #2ee6a8; }
    #layer-badge.button   { color: #7aa2f7; }
    #layer-badge.input    { color: #ffd700; }
    #add-hint { color: #6e7681; height: 1; }
    #statusbar {
        dock: bottom;
        height: 1;
        color: #9aa5b1;
        background: #161b22;
        padding: 0 1;
    }
    """

    def __init__(self, credential=None, interval=DEFAULT_INTERVAL):
        super().__init__()
        self.title = "基元律动 余额监控"
        self.keys = load_keys()
        self.active = None
        if credential:
            crd = parse_credential(credential)
            if crd.get("sess") or crd.get("sk"):
                self._add_key(credential, crd)
                self.active = 0
        elif self.keys:
            self.active = 0
        self.credential = credential
        self.interval = max(MIN_INTERVAL, min(int(interval), MAX_INTERVAL))
        self.sess_data = {}          # idx -> {me,wallet,usage}
        self.advanced = {}           # idx -> bool
        self.layer = LAYER_CONTAINER
        self.btn_index = 0           # 0=删除 1=前移 2=高级状态
        self._timer = None
        self._refreshing = False
        self._kb_render = 0
        self._last_ok = None

    def _active_cred(self):
        if self.active is None or not (0 <= self.active < len(self.keys)):
            return {}
        return parse_credential(self.keys[self.active]["raw"])

    def _add_key(self, raw, crd, activate=False):
        self.keys = [k for k in self.keys if k["raw"] != raw]
        self.keys.append({"name": key_name(raw, len(self.keys)), "raw": raw})
        if activate:
            self.active = len(self.keys) - 1
        save_keys(self.keys)

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Horizontal(id="main")
        # keybar：层指示 + 提示 + 添加输入，固定挂载一次避免重复 id
        keybar = Vertical(
            Horizontal(
                Static("▮ 容器", id="layer-badge"),
                Static("↑↓切层   ←→移动   Enter执行   R刷新   Q退出", id="add-hint"),
                id="keybar-top",
            ),
            PasteInput(placeholder="＋ 添加 sess…", id="key-add"),
            id="keybar",
            classes="hidden",
        )
        yield keybar
        yield Footer()
        yield Static("", id="statusbar")

    def on_mount(self) -> None:
        if self.keys:
            self._build_dashboard()
        else:
            self._build_credential_screen()

    def _clear_main(self):
        main = self.query_one("#main", Horizontal)
        for c in list(main.children):
            c.remove()

    def _build_credential_screen(self):
        self._clear_main()
        main = self.query_one("#main", Horizontal)
        # 首屏隐藏底部 keybar（无三态层）
        kb = self.query_one("#keybar")
        kb.add_class("hidden")
        pan = Vertical(
            Static("[bold cyan]基元律动 余额监控[/]"),
            Static("粘贴 sess 令牌，回车进入", id="cred-hint"),
            PasteInput(placeholder="sess_…（粘贴 sess 令牌，回车进入）",
                  id="cred-input"),
            id="cred-screen",
        )
        main.mount(pan)
        self.call_later(lambda: pan.query_one(Input).focus())

    def _build_dashboard(self):
        self._clear_main()
        main = self.query_one("#main", Horizontal)
        self._add_input_id = "key-add"
        # 显示底部 keybar（含三态层指示）
        kb = self.query_one("#keybar")
        kb.remove_class("hidden")
        self._rebuild_containers()
        self._start_timer()
        self._update_statusbar()
        self._fetch_now()
        self._set_layer(LAYER_CONTAINER)

    def _rebuild_containers(self):
        """结构性变化（增/删/前移）后重建所有 sess 容器。"""
        main = self.query_one("#main", Horizontal)
        for c in list(main.children):
            c.remove()
        if not self.keys:
            main.mount(Static("暂无 sess — 在底部输入框粘贴凭据串添加", id="empty-hint"))
            return
        for i, k in enumerate(self.keys):
            self._mount_container(main, i)

    def _mount_container(self, main, i):
        """挂载第 i 个 sess 容器（含基础字段 + 3 操作按钮）。
        不用固定 id：结构性重建可能在同一事件循环发生，重复 id 会 DuplicateIds。
        容器/按钮全部无 id，靠 DOM 顺序定位。children 通过构造器一次传入。"""
        pan = SessPanel(
            Static(self._sess_text(i), classes="sess-content"),
            Horizontal(
                Button("删除", classes="op-btn"),
                Button("前移", classes="op-btn"),
                Button("高级状态", classes="op-btn"),
                classes="ops",
            ),
            classes="sess",
        )
        pan.border_title = f" {self.keys[i]['name']} "
        if i == self.active:
            pan.add_class("active")
        main.mount(pan)

    def _sess_text(self, i):
        raw = self.keys[i]["raw"]
        data = self.sess_data.get(raw)
        if data is None:
            return "  [dim]加载中…[/]"
        text = _basic_fields(data)
        if self.advanced.get(raw):
            extra = _advanced_fields(data)
            if extra:
                text = text + "\n[dim]─ 高级状态 ─[/]\n" + extra
        return text

    def _refresh_container(self, i):
        """更新第 i 个容器的显示与 active 高亮（按 DOM 顺序定位，无 id）。"""
        pans = list(self.query("#main SessPanel"))
        if not (0 <= i < len(pans)):
            return
        # 该容器内容 Static 更新
        for child in pans[i].query(".sess-content"):
            if isinstance(child, Static):
                child.update(self._sess_text(i))
                break
        # active 高亮同步
        for idx, pan in enumerate(pans):
            if idx == self.active:
                pan.add_class("active")
            else:
                pan.remove_class("active")

    # ---------- 三态焦点 ----------

    def _set_layer(self, layer):
        self.layer = layer
        if layer == LAYER_CONTAINER:
            self._focus_container()
        elif layer == LAYER_BUTTON:
            self._focus_button()
        else:
            self._focus_input()
        self._refresh_badge()

    def _refresh_badge(self):
        """底部「当前层」指示，随层换色。"""
        label = {LAYER_CONTAINER: "容器", LAYER_BUTTON: "按钮", LAYER_INPUT: "输入"}.get(self.layer, "")
        try:
            b = self.query_one("#layer-badge", Static)
        except Exception:
            return
        b.remove_class("container")
        b.remove_class("button")
        b.remove_class("input")
        b.add_class(self.layer)
        b.update(f"▮ {label}")

    def _focus_container(self):
        if self.active is None or self.active >= len(self.keys):
            return
        for idx, pan in enumerate(self.query("#main SessPanel")):
            if idx == self.active:
                pan.add_class("active")
            else:
                pan.remove_class("active")
        # 清除按钮焦点样式
        for b in self.query("#main .op-btn"):
            b.remove_class("focused")
        # 让激活容器承接真实焦点（延迟到渲染后，避免被同批其它 focus 覆盖）
        pan = self._active_panel()
        if pan is not None:
            self.call_after_refresh(pan.focus)

    def _focus_button(self):
        if self.active is None:
            return
        btns = self._active_btns()
        if not btns:
            return
        for b in btns:
            b.remove_class("focused")
        if 0 <= self.btn_index < len(btns):
            btns[self.btn_index].add_class("focused")
            self.call_after_refresh(btns[self.btn_index].focus)

    def _active_btns(self):
        pan = self._active_panel()
        if pan is None:
            return []
        return list(pan.query(".op-btn"))

    def _active_panel(self):
        pans = list(self.query("#main SessPanel"))
        if self.active is not None and 0 <= self.active < len(pans):
            return pans[self.active]
        return None

    def _focus_input(self):
        # 清除按钮层高亮，避免残留
        for b in self.query("#main .op-btn"):
            b.remove_class("focused")
        if hasattr(self, "_add_input_id") and self._add_input_id:
            inp = self.query_one("#" + self._add_input_id, Input)
            # 延迟到渲染后聚焦，确保焦点稳定落在输入框
            self.call_after_refresh(inp.focus)

    def action_paste_into_input(self):
        """Ctrl+V 全局兜底：焦点不在输入框时，切到输入层并粘贴到底部输入框。
        焦点在输入框时由 Input 自带的 ctrl+v 处理（本 action 不会触发）。"""
        if self.layer == LAYER_INPUT:
            return
        self._set_layer(LAYER_INPUT)
        inp = self.query_one("#key-add", Input)
        if hasattr(inp, "action_paste"):
            inp.action_paste()

    # ---------- 方向键 ----------

    def action_layer_up(self):
        if self.layer == LAYER_INPUT:
            self._set_layer(LAYER_BUTTON)
        elif self.layer == LAYER_BUTTON:
            self._set_layer(LAYER_CONTAINER)

    def action_layer_down(self):
        if self.layer == LAYER_CONTAINER:
            self._set_layer(LAYER_BUTTON)
        elif self.layer == LAYER_BUTTON:
            self._set_layer(LAYER_INPUT)

    def action_nav_left(self):
        if self.layer == LAYER_CONTAINER:
            self._move_active(-1)
        elif self.layer == LAYER_BUTTON:
            self.btn_index = (self.btn_index - 1) % 3
            self._focus_button()

    def action_nav_right(self):
        if self.layer == LAYER_CONTAINER:
            self._move_active(1)
        elif self.layer == LAYER_BUTTON:
            self.btn_index = (self.btn_index + 1) % 3
            self._focus_button()

    def action_activate(self):
        if self.layer == LAYER_BUTTON:
            self._activate_btn(self.btn_index)
        elif self.layer == LAYER_CONTAINER:
            self._set_layer(LAYER_BUTTON)

    def _move_active(self, delta):
        if len(self.keys) <= 1:
            return
        self.active = (self.active + delta) % len(self.keys)
        self.btn_index = 0
        # 容器层切换：未拉取则补拉该容器数据
        raw = self.keys[self.active]["raw"]
        if raw not in self.sess_data:
            self._start_one_fetch(self.active)
        self._refresh_container(self.active)

    def _activate_btn(self, idx):
        if idx == 0:
            self.action_delete()
        elif idx == 1:
            self.action_move_forward()
        else:
            self.action_toggle_advanced()

    def action_toggle_advanced(self):
        if self.active is None:
            return
        raw = self.keys[self.active]["raw"]
        self.advanced[raw] = not self.advanced.get(raw, False)
        self._refresh_container(self.active)

    def action_delete(self):
        if not self.keys or self.active is None:
            return
        i = self.active
        raw = self.keys[i]["raw"]
        name = self.keys[i]["name"]
        del self.keys[i]
        self.sess_data.pop(raw, None)
        self.advanced.pop(raw, None)
        save_keys(self.keys)
        if not self.keys:
            self.active = None
            self.sess_data = {}
            self.advanced = {}
            self._build_credential_screen()
            self.notify(f"已删除 sess：{name}", timeout=3)
            return
        self.active = min(i, len(self.keys) - 1)
        self._rebuild_containers()
        self._fetch_now()
        self._set_layer(LAYER_CONTAINER)
        self.notify(f"已删除 sess：{name}", timeout=3)

    def action_move_forward(self):
        """前移：把当前 sess 往列表前部（索引小）移动一格。"""
        if not self.keys or self.active is None or self.active == 0:
            return
        i = self.active
        self.keys[i], self.keys[i - 1] = self.keys[i - 1], self.keys[i]
        self.active = i - 1
        save_keys(self.keys)
        self._rebuild_containers()
        self._set_layer(LAYER_CONTAINER)

    # ---------- 数据拉取 ----------

    def _fetch_now(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.run_worker(self._fetch_all_wrapper, group="fetch", exclusive=True)

    def _start_one_fetch(self, i):
        """补拉单个容器数据（在 worker 里跑）。"""
        self.run_worker(self._fetch_one_async(i), group="fetch")

    async def _fetch_all_wrapper(self):
        try:
            await self._fetch_all()
        finally:
            self._refreshing = False
            self._update_statusbar()

    async def _fetch_all(self):
        if not self.keys:
            return
        await asyncio.gather(*(self._fetch_one_async(i) for i in range(len(self.keys))),
                             return_exceptions=True)
        self._last_ok = time.strftime("%H:%M:%S")
        self._update_statusbar()

    async def _fetch_one_async(self, i):
        cred = parse_credential(self.keys[i]["raw"])
        token = cred.get("sess") or cred.get("sk")
        if not token:
            return
        raw = self.keys[i]["raw"]
        try:
            me, wallet, usage = await asyncio.gather(
                asyncio.to_thread(api_get, "/auth/me", token),
                asyncio.to_thread(api_get, "/wallet/summary", token),
                asyncio.to_thread(api_get, "/usage-summary", token),
            )
            self.sess_data[raw] = {"me": me, "wallet": wallet, "usage": usage}
            self._refresh_container(i)
        except Exception as e:
            self.notify(f"sess[{i}] 拉取失败: {e}", severity="error", timeout=4)

    # ---------- 刷新调度 ----------

    def _start_timer(self):
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._timer = self.set_interval(self.interval, self._on_tick)

    async def _on_tick(self) -> None:
        self._fetch_now()

    def action_refresh_now(self):
        self._fetch_now()

    def action_faster(self):
        self.interval = max(MIN_INTERVAL, self.interval // 2)
        self._start_timer()
        self._update_statusbar()

    def action_slower(self):
        self.interval = min(MAX_INTERVAL, self.interval * 2)
        self._start_timer()
        self._update_statusbar()

    def action_toggle_help(self):
        self.notify("↑↓切换层 ←→容器/按钮 R刷新 =/-间隔 Q退出", title="快捷键", timeout=4)

    # ---------- 输入提交（添加 sess） ----------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value
        crd = parse_credential(raw)
        if not (crd.get("sess") or crd.get("sk")):
            self.notify("未识别到 sess_ 或 sk_ 令牌，请检查输入。", severity="error", timeout=5)
            return
        if event.input.id == "key-add":
            self._add_key(raw, crd, activate=True)
            name = self.keys[self.active]["name"]
            event.input.value = ""
            self._rebuild_containers()
            self._fetch_now()
            self.notify(f"已添加 sess：{name}", timeout=4)
            self._focus_input()
        else:
            # 首页首个 sess
            self._add_key(raw, crd, activate=True)
            self._build_dashboard()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if "op-btn" not in event.button.classes:
            return
        # 按 DOM 顺序定位：找到按钮属于第几个容器
        pans = list(self.query("#main SessPanel"))
        for pan_idx, pan in enumerate(pans):
            btns = list(pan.query(".op-btn"))
            if event.button in btns:
                self.active = pan_idx
                action = event.button.label.plain if hasattr(event.button.label, "plain") else str(event.button.label)
                if action.startswith("删除"):
                    self.action_delete()
                elif action.startswith("前移"):
                    self.action_move_forward()
                elif action.startswith("高级"):
                    self.action_toggle_advanced()
                return

    def _update_statusbar(self):
        try:
            st = self.query_one("#statusbar", Static)
        except Exception:
            return
        n = len(self.keys)
        lay = {"container": "容器", "button": "按钮", "input": "输入"}[self.layer]
        last = self._last_ok or "…"
        st.update(f"  层:{lay}  sess {n}  │  刷新 {self.interval}s  │  上次 {last}  │  {API_BASE}")

    def on_unmount(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    credential = None
    interval = DEFAULT_INTERVAL
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-i", "--interval") and i + 1 < len(argv):
            try:
                interval = max(1, int(argv[i + 1]))
            except ValueError:
                pass
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        credential = " ".join(argv[i:])
        break
    BallanceTUI(credential=credential, interval=interval).run()


if __name__ == "__main__":
    main()