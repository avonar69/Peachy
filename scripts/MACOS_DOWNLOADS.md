---
kind: howto
---

### macOS 测试包

本次提供文件名含 `macos-x86_64.dmg` 的 Intel 安装镜像，Apple Silicon 原生制品不在本次范围。在「关于本机」中查看芯片或处理器。打开镜像，将 Peach 拖入「应用程序」，再打开应用完成首次设置。

应用内置 Python，可独立运行；单机使用不依赖 Windows。测试包使用 ad-hoc 签名，尚未完成 Developer ID 签名与 Apple 公证。媒体工具需另行准备，macOS 暂无在线更新安装器。系统版本下限以包内 `LSMinimumSystemVersion` 为准。

安装、来源挂载与双机复制见 [macOS 使用说明](https://github.com/avonar69/Peachy/blob/master/docs/OPERATIONS.md#macos-独立测试包)。Intel 原生构建、镜像挂载与独立运行通过后，DMG 随 Release 上传；哈希包含在 `SHA256SUMS.txt`。
