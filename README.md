# APAutoMuteBG

修改自开源项目 [AutoMuteBG](https://github.com/lingkai5wu/AutoMuteBG)（MIT License, Copyright (c) 2023 Wuu）。

本仓库地址：[github.com/stevenghost/APAutoMuteBG](https://github.com/stevenghost/APAutoMuteBG)

在原版"根据前后台自动调节进程音量"的基础上，增加了 **《蓝色星原：旅谣》剧情自动跳过** 功能。

## 功能

1. **后台静音**（原版功能）：目标进程切到后台时自动把音量降到设定值，回到前台恢复。
2. **剧情自动跳过**（新增）：
   - 检测游戏画面右上角的「>>」快进按钮，出现即连续点击，直到按钮消失；
   - 点击后若弹出「剧情梗概」遮罩，自动找到遮罩上的「跳过剧情」按钮并持续点击，直到遮罩消失；
   - 全程只读屏幕像素做匹配，不读写游戏内存，不改游戏文件。
3. **托盘菜单**：关于、开源地址、进程列表（导出 `process_name.txt`）、退出。

## 使用方法

### 首次使用

1. 下载 `background_muter.exe`（Releases 中的最新版本）。
2. 双击运行，程序会请求管理员权限（清单为 `requireAdministrator`），同意后在后台常驻。
3. 从任务托盘的右键菜单可以手动退出，也可随计算机关闭。

程序首次运行会在 exe 同目录生成 `config.yaml`，内容复制自 [default_config.yaml](resource/default_config.yaml)。

### 自定义配置

更改 `config.yaml` 后需要重启程序生效。默认配置中的 key 不可更改；若 key 有误，程序会备份原文件并重新生成。

- `setting`（程序设置）
  - `bg_scan_interval`（后台扫描间隔）：检测目标进程是否启动的时间间隔，单位秒。
  - `max_log_files`（最多日志文件数）：每次启动在 `logs/` 下生成日志；超过数量删除最早的；设为 `0` 不写日志。
  - `setup_msg`（启动通知）：启动完成是否显示通知，布尔值。

- `default`（默认配置）：所有进程的缺省值。
  - `loop_interval`（循环检测间隔）：检测前台窗口的时间间隔，单位秒；不建议大于 5 秒，否则后台关机时可能来不及恢复音量。
  - `fg_volume`（前台音量）：`[0, 1]` 或 `auto`。
  - `bg_volume`（后台音量）：`[0, 1]`。
  - `easing`（淡入淡出）：`duration`（秒）、`steps`（步数）；可设为 `null` 关闭。

- `processes`（单进程配置）：需要自动调节音量的进程，`null` 表示沿用默认配置。

  ```yaml
  processes:
    AzurPromilia.exe: null

    # 覆盖默认配置的写法
    cloudmusic.exe:
      fg_volume: auto
      bg_volume: 0.1
      easing: null
  ```

- `auto_click`（剧情自动跳过，新增）：只对 `process` 指定的进程生效，且**仅当该窗口位于前台时**工作。

  | 参数 | 默认值 | 说明 |
  | --- | --- | --- |
  | `enabled` | `true` | 是否启用自动跳过 |
  | `process` | `AzurPromilia.exe` | 目标进程名 |
  | `interval` | `0.1` | 按钮检测间隔（秒） |
  | `click_interval` | `0.1` | 命中后连点间隔（秒） |
  | `threshold` | `0.75` | 「>>」按钮的匹配阈值（0~1，越大越严格） |
  | `center_x` / `center_y` | `2408` / `61` | 按钮中心坐标（**2560×1440 客户区**） |
  | `search` | `3` | 匹配时的滑动搜索半径（像素） |
  | `max_blue_shift` | `30` | 区域 B−R 均值超过此值判为蓝色光效，不当作按钮 |
  | `stop_misses` | `6` | 连续多少次检测不到才认为按钮消失（0.1s/次 ≈ 0.6s 容错） |
  | `cooldown` | `0.2` | 一轮连点结束后的冷却（秒） |
  | `max_click_seconds` | `30` | 单轮连点最长时间，防止误判死循环 |
  | `overlay_x` / `overlay_y` | `1720` / `1078` | 遮罩上「跳过剧情」按钮中心（2560×1440） |
  | `overlay_threshold` | `0.70` | 「跳过剧情」按钮的匹配阈值 |
  | `overlay_search` | `4` | 遮罩按钮的滑动搜索半径 |
  | `overlay_max_seconds` | `15` | 遮罩连点最长时间 |
  | `overlay_click_interval` | `0.1` | 遮罩连点间隔（秒） |

### 分辨率适配

内置模板按 **2560×1440**、窗口化/无边框模式实测裁剪，保存在：

- `resource/azur_skip.npy`：右上角「>>」按钮，64×64 灰度
- `resource/azur_skip_story.npy`：遮罩「跳过剧情」按钮，240×48 灰度

换分辨率或 UI 缩放后，需要重新截取游戏画面、按同样尺寸裁剪模板，并同步调整 `center_x` / `center_y`（以及遮罩的 `overlay_x` / `overlay_y`）。模板为 `.npy` 灰度数组，可用 Pillow + NumPy 生成：

```python
from PIL import Image
import numpy as np

img = Image.open("screenshot.png").convert("L")
crop = np.asarray(img.crop((left, top, left + 64, top + 64)), dtype=np.uint8)
np.save("resource/azur_skip.npy", crop)
```

### 自行构建

需要 Python 3.13、`pip install -r requirements.txt`，以及 PyInstaller。

```powershell
cd tools/AutoMuteBG
.\build.ps1
```

`build.ps1` 会：

1. 用 PyInstaller 以 onedir 方式构建（带 `requireAdministrator` 清单）；
2. 从本机证书库查找自签名证书并给 exe 签名；
3. 打印签名状态。

签名是可选的：没有证书时跳过即可（首次运行仍会请求管理员权限，只是 UAC 会显示"未知发布者"）。自签名证书只对安装了该证书的机器有效，**不要**把证书私钥或 `cert/` 提交到仓库。

### 已知问题

- **强制关闭程序（例如任务管理器）时，目标进程的音量不会自动恢复**，重新启动程序或在音量合成器中重置即可。
- 部分环境下 `Shell_NotifyIcon` 可能失败导致**托盘图标不显示**（日志中有 `Tray diagnostics` 行），此时程序仍在运行，可通过任务管理器结束。
- 自签名发布者的 exe 在其他电脑上会显示"未知发布者"；SmartScreen 是否拦截取决于文件来源与信誉。
- ~~有时会忘记自己还在打游戏~~。

