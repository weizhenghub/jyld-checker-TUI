# 使用TUI直观管理多个基元律动账号额度

<img width="1113" height="621" alt="image" src="https://github.com/user-attachments/assets/b37b673c-b285-46f5-81dc-f77e565f2480" />


基于https://github.com/xmbl4399/jyld-balance-checker 二创，感谢作者xmbl4399。
在原所有功能的基础上，使用TUI进行多key管理，统一监控。

🔑 凭据智能解析：支持整体粘贴 ---- 分隔的凭据串，自动识别手机号、sess_ 会话令牌、sk_ API Key、rf_ 刷新令牌、UUID（最少只需 sess_ 一段即可查询）
📊 三接口查询：账号信息（/auth/me）+ 钱包余额（/wallet/summary）+ 用量统计（/usage-summary），并行拉取、一次展示
📈 TUI 仪表盘：每个 sess 一个容器，默认显示 用户名 / 手机号 / 状态 / 可用余额 / 赠送，点「高级状态」展开全部字段
🔄 自动容错：优先用 sess_ 会话令牌，失败自动尝试 sk_ API Key
🗂️ 多 sess 管理：容器内「删除 / 前移」按钮管理列表，底部输入框随时新增
📦 依赖：CLI 版零依赖（仅 Python 标准库，3.8+）；TUI 版需 `pip install textual`（Python 3.9+）
🖥️ 双击即用：`jyld_tui.bat` 一键启动 TUI


控制：
使用键盘上下键控制层
第一层：在容器之间切换（←/→ 切换下一个容器）
第二层：当前选中的容器内按钮（←/→ 在「删除 / 前移 / 高级状态」间移动，Enter 执行）
第三层：输入框，输入sess来新增（粘贴后 Enter 添加）
此处显示了您位于哪一层  
<img width="157" height="115" alt="image" src="https://github.com/user-attachments/assets/99de81b9-659c-48b1-ad2a-f07c8d30ce74" />
<img width="151" height="103" alt="image" src="https://github.com/user-attachments/assets/c07458c2-f4af-4687-943d-11500cdfc482" />
<img width="167" height="102" alt="image" src="https://github.com/user-attachments/assets/1c282d2f-64f1-4c2a-b5d8-91f9d284808d" />

## 使用方法

安装依赖（TUI 版）：
```
pip install textual
```

启动：
```
python jyld_tui.py        # 或直接双击 jyld_tui.bat
```

- 首次启动：粘贴 sess 令牌（如 sess_xxx），回车进入
- 添加更多 sess：在底部输入框粘贴新 sess，回车即添加并激活
- 切换：容器层 ←/→ 切换容器；按钮层 ←/→ 选按钮，Enter 执行；↑/↓ 在 容器 / 按钮 / 输入 三层间升降
- 快捷键：R 立即刷新，= / - 调整刷新间隔（默认 30 秒），Q 退出，? 快捷键提示，Ctrl+V 粘贴

数据说明：sess 令牌保存在本地 `creds.json`（已 gitignore，不会提交），工具仅用于查询自己账号的额度信息。

## 开源说明

基于 [xmbl4399/jyld-balance-checker](https://github.com/xmbl4399/jyld-balance-checker) 二创，感谢作者 xmbl4399。
本仓库以 [MIT](LICENSE) 协议开源。工具仅用于查询自己账号的余额 / 额度信息，请勿用于任何未授权的用途。
