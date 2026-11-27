# V 键随机投掷物

空手按 **V**，自动拿起并投出砖块、硬盘、艺术摆件或玩偶中的一件。已有手持物时保留当前物品。自动投掷使用默认鼠标左键轻攻击绑定。

适用 Windows Epic 版《师父》`v_1.29_6.770`。以 `Sifu-Win64-Shipping.exe` 所在目录为 `Sifu/Binaries/Win64`。

## 安装

1. 退出游戏。首次使用时先安装支持 EngineTick 的 UE4SS，可用本仓库的[时停 Release](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/time-stop-v1.0.0)提供的兼容加载器。
2. 解压 `Sifu-RandomThrowable-Epic-6770.zip`，把包内 `Win64` 的内容合并到游戏的 `Sifu/Binaries/Win64/`。
3. 启动游戏，在可操作时空手按 **V**。

若已有同名 `SifuThrowStun` 目录，请先将旧目录备份到游戏目录外，再复制新文件。

覆盖已有文件前，把原文件备份到游戏目录外。

## 卸载

退出游戏，移出 `Sifu/Binaries/Win64/ue4ss/Mods/SifuThrowStun`。

## 开发

`SifuThrowStun/` 是安装包中的 Lua 模组源码。使用 64 位 MinGW GCC 构建 `InputBridge.c`，输出到 `SifuThrowStun/Scripts/ThrowableInputBridge.dll`。

[安装包](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/random-throwable-v1.0.0)
