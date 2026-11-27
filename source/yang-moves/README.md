# 杨招式

这是本机正在使用的推踢特效版。空手按 **Z** 发动霸体推踢，附聚能光幕、气浪、扬尘和命中特效。**X** 为冲刺扫腿，**C** 为三连击，**G** 为闪现五连拳。

适用 Windows Epic 版《师父》`v_1.29_6.770`。以 `Sifu-Win64-Shipping.exe` 所在目录为 `Sifu/Binaries/Win64`。

## 安装

1. 退出游戏。首次使用时先安装支持 EngineTick 的 UE4SS，可用本仓库的[时停 Release](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/time-stop-v1.0.0)提供的兼容加载器。
2. 解压 `Sifu-Yang-Impact-Push-Kick-Epic-6770.zip`。如果已安装杨招式，先把旧 `SifuYangMoves` 目录和同名 `.pak`、`.sig` 备份到游戏目录外。
3. 把 ZIP 的 `Paks/~mods` 中两个文件放入游戏 `Sifu/Content/Paks/~mods/`，把 ZIP 的 `Win64` 内容合并到游戏 `Sifu/Binaries/Win64/`。
4. 启动游戏，在训练中空手测试 Z、X、C、G。

处决领域也会用到默认 **X** 键。遇到按键冲突时，先单独测试一个模组。

如果缺少 `~mods`，可在游戏的 `Sifu/Content/Paks` 下新建。覆盖已有文件前，把原文件备份到游戏目录外。

## 卸载

退出游戏，移出 `Sifu/Binaries/Win64/ue4ss/Mods/SifuYangMoves` 和 `~mods` 中的 `pakchunk98-YangMoves_P.pak`、`pakchunk98-YangMoves_P.sig`。

## 开发

`SifuYangMoves/` 和 `ComboPatch/` 是当前 Lua 与 C# 资产补丁源码。`InputBridge.c` 用 64 位 MinGW GCC 编译为 `YangInputBridge.dll`。重建 Pak 需要 .NET 10、UAssetAPI、repak 和与游戏版本对应的本机原始资产。

[安装包](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/yang-moves-v1.0.0)
