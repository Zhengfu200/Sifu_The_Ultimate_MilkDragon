# Sifu The Ultimate MilkDragon

《师父》Windows Epic `v_1.29_6.770` 的奶龙角色替换 Mod 工程。男主默认服装对应普通奶龙。现有本机包的 Rysrin 栏位对应斗笠长披风版。

## 安装

取得对应游戏版本的 Mod ZIP 后，退出游戏并解压。把 `pakchunk99-Nailoong_P.pak` 和 `pakchunk99-Nailoong_P.sig` 直接放进游戏安装目录内的 `Sifu/Content/Paks/~mods`。如果没有 `~mods`，在 `Paks` 内新建。已有同名文件时，先将原先的一对备份到游戏目录外。启动后在男主衣柜切换到对应服装。卸载时退出游戏，移走这两个文件，有需要时复制回备份。

## 工程

- `scripts/` 包含 Blender 模型处理、UE 导入与打包、服装和握持挂点工具。
- `ue/` 包含 Unreal Engine 4.26.2 项目配置及 SifuModTools 插件源码。
- `source/nailoong/` 包含练习用的奶龙 Blender 原模型和有署名许可的配件。
- [开发记录](docs/开发记录.md) 保留各次调整和本机验证情况。其中的 `build/` 路径指开发机生成产物。

本地构建使用 Blender、PowerShell 7、Unreal Engine 4.26.2、.NET 10、[repak](https://github.com/trumank/repak) 和 [UAssetAPI](https://github.com/atenfyr/UAssetAPI)。构建脚本预期分别在 `tools/repak`、`tools/dotnet` 和 `tools/UAssetAPI` 下找到相应工具。游戏骨架、服装蓝图等参考输入需从本地对应版本游戏取得并放入脚本指定的 `local/reference` 路径。握持挂点配置见 [grip-sockets.json](docs/grip-sockets.json)。

## 素材署名

- 奶龙 Blender 模型由 WeDai 制作并分享，用于学习和练习。奶龙角色形象版权归其权利人所有。[原始模型仓库及使用说明](https://github.com/bigdiu/naiwa-nailoong-blender-model#七版权说明)
- 背部披风基于 hate（@haters）的 Cape，调整了版型、长度、材质、衬里和蒙皮，并加入布料模拟。[Cape](https://sketchfab.com/3d-models/cape-61e185ae00b640258071c581ab40f749) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 斗笠基于 eeelabvisual 的 SIRUNG Conical Hat，调整了比例、位置、倾角和绑定。[SIRUNG Conical Hat](https://sketchfab.com/3d-models/sirung-conical-hat-83c5b31a35b54052bfd43da6ad37db21) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 本机同济版使用的校徽来自同济视觉形象素材，权利归同济大学或实际权利人。[素材来源及版权声明](https://github.com/TJ-CSCCG/tongji-visual#免责--声明)
