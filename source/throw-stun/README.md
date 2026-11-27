# V 键投掷眩晕

战斗中按 **V** 自动向最近的最多 **5 名可见敌人**各投出一个酒瓶，命中时施加约 **1.8 秒眩晕**。酒瓶不消耗手持物，也不直接造成生命伤害。

适用 Windows Epic 版《师父》`v_1.29_6.770`。以 `Sifu-Win64-Shipping.exe` 所在目录为 `Sifu/Binaries/Win64`。

## 安装

1. 退出游戏。首次使用时先安装支持 EngineTick 的 UE4SS，可用本仓库的[时停 Release](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/time-stop-v1.0.0)提供的兼容加载器。
2. 解压 `Sifu-ThrowStun-Epic-6770.zip`，把 `Win64` 的内容合并到游戏的 `Sifu/Binaries/Win64/`。
3. 启动游戏，进入训练或剧情战斗，对着有可见目标的区域按 **V**。

两个 **V** 键版本共用 `SifuThrowStun` 目录。使用其中一个版本，切换前将旧版本目录移出 `Mods` 后再复制新文件。

覆盖已有文件前，把原文件备份到游戏目录外。

## 卸载

退出游戏，移出 `Sifu/Binaries/Win64/ue4ss/Mods/SifuThrowStun`。

## 开发

工作源码位于 `SifuThrowStun/`，安装包的 Lua 快照位于 `release-source/`。`DizzyBridge.c` 使用 64 位 MinGW GCC 编译。原始开发记录中的两个 V 键版本沿用了同一模块目录名。

[安装包](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/throw-stun-v1.0.0)
