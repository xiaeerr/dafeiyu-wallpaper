# Dafeiyu Wallpaper · 大肥鱼桌面陪伴

Dafeiyu Wallpaper is a standalone interactive desktop companion for Windows. It connects to AstrBot for chat and supports voice replies, a memory map, and a fullscreen demo.

## 在 Windows 上启动

安装带 Tcl/Tk 的 Python 3.12 或更新版本和 Microsoft Edge。打开 PowerShell，进入仓库目录：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe .\launch.pyw
```

- `launch.pyw` 把壁纸挂到 Windows 桌面。想先看全屏效果，可运行 `.\.venv\Scripts\pythonw.exe .\demo.pyw`，按 **Alt+F4** 退出演示。
- 首次配置时，在浏览器打开 `http://127.0.0.1:18766/` 设置 AstrBot 密钥，打开 `http://127.0.0.1:18766/app/voice-settings.html` 设置语音。平时可拖动聊天框标题栏、拉伸四边，点 **↩** 恢复原位。
- 若要登录后启动，可在 Windows 的启动文件夹添加快捷方式，目标为虚拟环境的 `pythonw.exe`，参数为 `"仓库绝对路径\launch.pyw" --startup`。

桌面中文输入默认使用 Python 的 Tk 辅助窗口。如需使用 WinForms 版，可在仓库目录编译随附的源码：

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:winexe /platform:x64 /r:System.Web.Extensions.dll /out:NativeChatInput.exe NativeChatInput.cs
```

下次启动本地服务时会优先使用编译出的辅助程序。

## 连接 AstrBot

1. 启动 AstrBot。将 `DAFEIYU_ASTRBOT_CORE` 环境变量指向包含 AstrBot `main.py` 和 `data` 的目录，再启动壁纸。
2. 在 AstrBot 创建有聊天权限的 API 密钥，通过本地配置页保存。默认使用 AstrBot 的模型设置。需要指定提供方时，设置 `DAFEIYU_ASTRBOT_PROVIDER`。
3. 建议先安装 **LivingMemory** 并聊到它生成第一条情节记忆，再打开星图。已有核心记忆或璃笺日记时，星图也会一起显示。图片上传和部分插件记忆编辑需要通过 `DAFEIYU_ASTRBOT_MAINTENANCE_KEY` 提供有对应 `file` 或 `plugin` 权限的密钥。
4. MiniMax 和 CosyVoice 可分别在语音设置页配置。使用本地声线需要另行安装兼容的运行时和权重。

程序默认只监听 `127.0.0.1:18766`。可用 `DAFEIYU_PORT` 改端口。状态默认保存于用户目录下的 `.dafeiyu-wallpaper-release`，可用 `DAFEIYU_STATE_DIR` 单独指定。每个安装会生成自己的本地连接令牌。云语音调用可能计费，截图功能会把画面随消息发给所配置的 AstrBot。

## 记忆插件与人格配置

| AstrBot 插件 | 星图读取的内容 |
| --- | --- |
| LivingMemory（`astrbot_plugin_livingmemory`） | 情节记忆、已有的情绪标签和记忆要点 |
| 核心记忆（`astrbot_plugin_yuren_core`） | 核心、潜意识、小事三级记录 |
| 璃笺（`astrbot_plugin_lijian`） | 未归档日记 |
| 作息（`astrbot_plugin_yuren_night`） | 右侧面板的睡眠状态 |

这些插件按需安装。没有对应数据时，星图可以打开，相应分类会为空。星图负责读取和展示；聊天时能否回忆起来，取决于 AstrBot 中实际启用的记忆检索、上下文注入和工具权限。

想调自然一点的聊天语气，可以从[桌面人格书写教程](docs/persona-guide.md)开始。里面有可粘贴的模板、可选插件、语音与主动闲聊的能力边界，以及建议用来试聊的场景。

## 项目来源与发布范围

本项目基于 [Deepseek 图鲸鲸 · 大肥鱼数字生命控制台](https://steamcommunity.com/sharedfiles/filedetails/?id=3820189840)，沿用原壁纸的角色形象、场景和互动，并添加独立桌面启动、AstrBot 聊天、语音和星图。字体随附原许可文本。AstrBot、外部记忆插件、模型和声音素材由使用者自行安装，并遵循各自许可。

这份目录用于本地发布预览。新增代码的开源许可待仓库所有者确定。公开前请核实原壁纸代码和素材的再分发授权。
