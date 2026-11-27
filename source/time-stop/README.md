# T 键时停

按 **T** 切换时停效果。开启时显示黑白专注滤镜，世界以 **0.10 倍速**运行，角色动作和骨骼动画的目标速度为 **1.50 倍**。再次按 T 恢复。原版 **F** 键专注可照常使用。

适用 Windows Epic 版《师父》`v_1.29_6.770`。以 `Sifu-Win64-Shipping.exe` 所在目录为 `Sifu/Binaries/Win64`。

## 安装

1. 退出游戏并解压 `Sifu-TimeStop-Epic-6770.zip`。
2. 已有 UE4SS 时，先备份游戏目录里的 `dwmapi.dll` 和 `ue4ss`。如果加载器已兼容，可仅复制 `Win64/ue4ss/Mods/SifuTimeStop` 到现有的 `Sifu/Binaries/Win64/ue4ss/Mods/`。
3. 首次安装时，把 ZIP 内 `Win64` 的内容合并到 `Sifu/Binaries/Win64/`，与 `Sifu-Win64-Shipping.exe` 同级。
4. 正常启动游戏，在自由训练按 **T** 开启，再按 **T** 恢复。

安装包附带 UE4SS `v4.0.0-9-gb2d936b9`、对应游戏版本的 `VTableLayout.ini` 和 UE4SS 的 MIT 许可证。 [UE4SS 官方实验版](https://github.com/UE4SS-RE/RE-UE4SS/releases/tag/experimental-latest)

覆盖已有文件前，把原文件备份到游戏目录外。

## 卸载

退出游戏，移出 `Sifu/Binaries/Win64/ue4ss/Mods/SifuTimeStop`。若 UE4SS 只用于本模组，可同时移出此次安装的加载器。已有其他 UE4SS 模组时保留共享加载器。

## 开发

开发源码包含 Lua 脚本和游戏版本配置。修改脚本后可替换本地模组目录中的 `Scripts/main.lua` 并重启游戏。构建包采用与发布 ZIP 相同的目录布局。

[安装包](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/time-stop-v1.0.0)
