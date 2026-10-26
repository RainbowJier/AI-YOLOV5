# 鼠标驱动 DLL

`app-cs2/native/mouse_driver.c` 编出 `app-cs2/native/mouse_driver.dll`，由
`config.mouse_driver = "dll"` 启用（默认）。它取代了原来的 sendinput 路径
（pywin32 `mouse_event`）：同样发
`MOUSEEVENTF_MOVE`，但整条路径不再穿 Python。

## 为什么值得换

- **少一次每帧的 Python→C 往返**：原来的 `win32api.mouse_event()` 每次调用都要过 pywin32
  封送和一次 `user32` 查找，`md_move` 是一次扁平 cdecl 调用。
- **不丢小数**：`targeting._smooth()` 返回浮点位移，旧路径 `int(x)` 会把 0.4px 的
  微调截成 0。DLL 内部累积余量，连续小位移最终会落到屏幕上。
- **可选定时器精度**：`config.dll_timer_ms = 1` 会在进程内 `timeBeginPeriod(1)`，
  让注入的输入更均匀；退出时由 `md_shutdown()` 还原。

## 编译（仅重编时需要）

`mouse_driver.dll` 已随仓库自带，平时无需编译。改了 `mouse_driver.c` 才需要重编：
需要 “Build Tools for Visual Studio” 的 C++ 工作负载 + Windows SDK（不需要完整 VS）。
从开始菜单打开 “x64 Native Tools Command Prompt for VS”（载入 MSVC + SDK 环境），
在仓库根目录执行（中间产物落 `%TEMP%`，仓库里不留 .obj/.lib/.exp）：

```bat
cl /nologo /LD /O2 /W4 /EHsc /DNDEBUG app-cs2\native\mouse_driver.c /Fo"%TEMP%\mouse_driver.obj" /link /OUT:app-cs2\native\mouse_driver.dll /IMPLIB:"%TEMP%\mouse_driver.lib" user32.lib winmm.lib
```

忘了链 `user32.lib` 会报 `LNK2019: __imp_SendInput`；源文件保持纯 ASCII，否则
中文代码页（936）下会触发 C4819。

## 导出函数

| 函数 | 说明 |
| --- | --- |
| `int md_init(void)` | 初始化，返回 1 成功 |
| `void md_shutdown(void)` | 复位状态、还原定时器精度 |
| `int md_move(float dx, float dy)` | 相对位移，带小数累积；返回 1 表示已发出 |
| `int md_move_exact(int dx, int dy)` | 不做累积的整数位移 |
| `int md_set_timer_resolution(unsigned ms)` | 0 关闭；非 0 为 `timeBeginPeriod` 毫秒 |
| `int md_get_sent(void)` | 已成功注入的输入条数 |

`app-cs2/aimbot/driver.py` 里的 `DllDriver` 只绑 `md_init` / `md_move` /
`md_set_timer_resolution` / `md_shutdown`。

## 排查

- 启动打印 `DLL file not found`：`app-cs2/native/mouse_driver.dll` 缺失或损坏，按上文重编，或把 `config.mouse_driver` 换成 `logitech`。
- 鼠标不动但 `ok` 为真：确认 Caps Lock、`aim_range`、以及游戏是否以前台窗口接收输入。
