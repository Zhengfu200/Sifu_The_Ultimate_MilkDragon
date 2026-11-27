# 杨招式

将杨的招式映射到四个键。**Z** 推踢，**X** 冲刺扫腿，**C** 三连击，**G** 连续拳。七个安装包共用模组目录和 Pak 名称，**只安装其中一个**。

适用 Windows Epic 版《师父》`v_1.29_6.770`。以 `Sifu-Win64-Shipping.exe` 所在目录为 `Sifu/Binaries/Win64`。

## 选择安装包

| ZIP 文件名中的版本 | 效果 |
| --- | --- |
| `MultiHit-G` | G 键五段拳，关闭格挡与招架，敌人仍可闪避。 |
| `5Hit-G-1.5x` | G 键原地五连拳，1.5 倍出招速度。 |
| `5Hit-G-Blink` | G 键闪现贴近目标后五连拳，1.5 倍出招速度。 |
| `15Hit-G-1.5x` | G 键三轮五连拳，共十五拳，1.5 倍出招速度。 |
| `Powered-Push-Kick` | 强化 Z 键推踢，附倒地和更高击退。 |
| `Armored-Push-Kick` | 在强化推踢基础上，出招期间提高抗硬直。 |
| `Impact-Push-Kick` | 霸体强化推踢，附聚能、气浪、扬尘和命中特效。 |

## 安装

1. 退出游戏。首次使用时先安装支持 EngineTick 的 UE4SS，可用本仓库的[时停 Release](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/time-stop-v1.0.0)提供的兼容加载器。
2. 从 Release 中选一个变体 ZIP。此前装过另一变体时，先把旧 `SifuYangMoves` 目录和同名 `.pak`、`.sig` 移出游戏目录。
3. 把 ZIP 的 `Paks/~mods` 中两个文件放入游戏 `Sifu/Content/Paks/~mods/`，把 ZIP 的 `Win64` 内容合并到游戏 `Sifu/Binaries/Win64/`。
4. 启动游戏，在训练中空手测试 Z、X、C、G。

处决领域也会用到默认 **X** 键。遇到按键冲突时，先单独测试一个模组。

如果缺少 `~mods`，可在游戏的 `Sifu/Content/Paks` 下新建。覆盖已有文件前，把原文件备份到游戏目录外。

## 卸载

退出游戏，移出 `Sifu/Binaries/Win64/ue4ss/Mods/SifuYangMoves` 和 `~mods` 中的 `pakchunk98-YangMoves_P.pak`、`pakchunk98-YangMoves_P.sig`。

## 开发

`SifuYangMoves/` 和 `ComboPatch/` 是当前 Lua 与 C# 资产补丁源码。`InputBridge.c` 用 64 位 MinGW GCC 编译为 `YangInputBridge.dll`。`variants/` 保存七个现有 ZIP 的 Lua 和原包说明；`history/` 保存可找到的早期 C# 与 Lua 开发版本。重建 Pak 需要 .NET 10、UAssetAPI、repak 和与游戏版本对应的本机原始资产。历史 Lua 快照不包含完整的历史构建输入。

[安装包](https://github.com/Zhengfu200/Sifu_The_Ultimate_MilkDragon/releases/tag/yang-moves-v1.0.0)
