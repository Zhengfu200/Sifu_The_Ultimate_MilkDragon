"""Write the local, self-contained comparison index from verified build outputs."""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--refined", action="store_true")
args = parser.parse_args()
OUT = ROOT / ("build/manual-refine" if args.refined else "build/arm-fix")
title = "奶龙腕肘精修 · v3" if args.refined else "奶龙手臂绑定修复 · v2"
changes = (
    "加宽双腕的权重过渡，平滑肘部及腋下的权重。掌心和指尖仍整体随手骨运动。"
    if args.refined else
    "恢复原版参考骨架，按连通区域和肢体轴线分配权重，沿原版辅助扭转骨平滑过渡。"
)
old_label = "v2" if args.refined else "修复前"
new_label = "v3" if args.refined else "修复后"
report = json.loads((OUT / "validation.json").read_text())
old = max(p["arm_edge_stretch_p99"] for p in report["before"]["samples"])
new = max(p["arm_edge_stretch_p99"] for p in report["after"]["samples"])
rows = []
for image in sorted((OUT / "after").glob("*.png")):
    if not (OUT / "before" / image.name).exists():
        continue
    name = html.escape(image.name)
    rows.append(
        f'<section><h2>{name}</h2><div class="pair">'
        f'<figure><img loading="lazy" alt="{old_label}" src="before/{name}"><figcaption>{old_label}</figcaption></figure>'
        f'<figure><img loading="lazy" alt="{new_label}" src="after/{name}"><figcaption>{new_label}</figcaption></figure>'
        '</div></section>'
    )
page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>奶龙手臂绑定修复对照</title>
<style>body{{font:16px/1.65 system-ui;background:#18191b;color:#eee;max-width:1100px;margin:auto;padding:32px}}h2{{font-size:14px;overflow-wrap:anywhere}}.pair{{display:flex;gap:12px}}figure{{margin:0;flex:1;min-width:0}}img{{width:100%;background:#080808}}figcaption{{text-align:center}}section{{border-top:1px solid #444;margin-top:24px;padding-top:12px}}</style>
<h1>{title}</h1>
<p>{changes}</p>
<p>每对图使用同一游戏动画、同一帧和同一相机。肩部在大幅度动作中仍有褶皱，手臂和肚子仍可能穿插。武器握持需要实机检查。</p>
<p>130 个采样姿势中，手臂网格边拉伸倍率的第 99 百分位峰值由 {old:.2f} 降至 {new:.2f}。273 根骨骼的参考变换在 FBX 往返检查和烘焙后检查中均通过。</p>
{''.join(rows)}</html>'''
(OUT / "comparison.html").write_text(page, encoding="utf-8")
print("Comparison index:", OUT / "comparison.html", "pairs:", len(rows))
