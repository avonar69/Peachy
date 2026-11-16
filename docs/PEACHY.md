# Peachy 分支与发行

Peachy 基于 Peach，按 AGPL-3.0-or-later 提供源代码与发行包。原项目许可证、作者归属与第三方工具对应源码继续保留。

`master` 是定制功能发行分支。上游 `peach-mitao/peach:master` 的更新进入单独兼容性 PR，完成差异审阅与测试后再决定是否合入；待复核代码不随当前发行发布。

## 桌面发行

发行入口为 Actions 的 **Publish Peachy**。该流程在 `master` 上调用 `scripts/release_tag.py`，要求同一提交的 Test 已通过，核对版本与变更日志后创建标签，再启动 Release。Release 分别构建 Windows x64、macOS arm64 与 x86_64；安装与独立运行验收通过后才上传公开测试版及 SHA256 清单。

首次发行沿用代码中的 `0.46.1`，发行名为 Peachy。内部 `peach` Python 包、`Peach.exe`、`Peach.app`、`Peach-*` 制品与数据目录保持现有格式；安装显示名称和发行入口属于 Peachy，应用更新与轻量安装工具包仅从本 fork 获取。macOS 制品使用 ad-hoc 签名，不含 Apple 公证。

Windows 首次安装选完整安装包或完整 ZIP；更新包与独立工具包用于已有安装。macOS 根据芯片选择 arm64 或 x86_64 DMG。兼容性保留不表示两个分支可同时使用同一数据目录；每个运行实例应使用独立的数据目录与端口。
