"use strict";
// single-gpu-local-ai の紹介スライド（10 枚前後）を作る。数字はすべてこのリポジトリの記録から取った値で、各スライドのノートに根拠を書く。
//
//   mkdir -p /tmp/slides-tool && cd /tmp/slides-tool && npm init -y && npm install pptxgenjs jszip
//   NODE_PATH=/tmp/slides-tool/node_modules \
//   GITHUB_USER=<ユーザー名> PPTX_APPLY_THEME=<pptx スキルの scripts/apply_theme.js> \
//     node docs/slides/build-deck.js docs/slides/localai-portfolio.pptx
//
// PPTX_APPLY_THEME を渡すと、テーマの色（scheme color）をファイルに書く。渡さないと Office の既定の色になる。
const pptxgen = require("pptxgenjs");

const OUT_PATH = process.argv[2] || "localai-portfolio.pptx";
const GITHUB_USER = process.env.GITHUB_USER || "<user>";
const REPO_LABEL = `github.com/${GITHUB_USER}/single-gpu-local-ai`;
const PAGES_LABEL = `${GITHUB_USER}.github.io/single-gpu-local-ai`;
const FONT = "Yu Gothic";

const THEME = {
  name: "single-gpu-local-ai",
  headFontFace: FONT,
  bodyFontFace: FONT,
  colors: {
    dk1: "1B1F24",
    lt1: "FFFFFF",
    dk2: "14213D",
    lt2: "EEF1F5",
    accent1: "0F766E", // teal: Ollama・主役
    accent2: "F2A93B", // amber: 暗い背景の上の強調
    accent3: "2F5FA8", // blue: Claude
    accent4: "B4533C", // terracotta: 注意
    accent5: "6B4FA3", // violet: Strata
    accent6: "5B6470", // gray: 補助
    hlink: "0F766E",
    folHlink: "6B4FA3",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 inch
pres.title = "single-gpu-local-ai — 24 GB の GPU 1 枚で、ローカル AI の群れを運用し、測る";
pres.author = GITHUB_USER;
pres.subject = "ローカル AI の運用・評価・連携";
pres.theme = { headFontFace: FONT, bodyFontFace: FONT };

const C = pres.SchemeColor;
const S = pres.shapes;
const HEX = THEME.colors;

// ---------------------------------------------------------------- レイアウト
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: HEX.dk2 },
  objects: [],
});

pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.lt1 },
  objects: [
    {
      placeholder: {
        options: {
          name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.85,
          fontSize: 30, bold: true, color: C.text2, align: "left", valign: "middle", margin: 0,
        },
        text: "",
      },
    },
    { text: { text: "single-gpu-local-ai", options: { x: 0.5, y: 5.2, w: 3, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: HEX.dk2 },
  objects: [
    {
      placeholder: {
        options: {
          name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.85,
          fontSize: 30, bold: true, color: C.background1, align: "left", valign: "middle", margin: 0,
        },
        text: "",
      },
    },
  ],
});

// ---------------------------------------------------------------- 部品
function card(slide, name, x, y, w, h) {
  slide.addShape(S.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: C.background2, width: 0.5 }, objectName: name,
  });
}

function numberDot(slide, name, label, x, y, size) {
  slide.addText(label, {
    shape: S.OVAL, x, y, w: size, h: size, fill: { color: C.accent1 }, color: C.background1,
    fontSize: 16, bold: true, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: name,
  });
}

function label(slide, name, text, x, y, w, h, options = {}) {
  slide.addText(text, {
    x, y, w, h, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: name, ...options,
  });
}

function box(slide, name, text, x, y, w, h, fillColor, textColor, fontSize = 12) {
  slide.addText(text, {
    shape: S.ROUNDED_RECTANGLE, rectRadius: 0.06, x, y, w, h, fill: { color: fillColor }, line: { color: fillColor, width: 0.5 },
    color: textColor, fontSize, align: "center", valign: "middle", margin: 4, isTextBox: true, objectName: name,
  });
}

function arrow(slide, name, x, y, w, h, color = C.accent6) {
  slide.addShape(S.LINE, { x, y, w, h, line: { color, width: 1.5, endArrowType: "triangle" }, objectName: name });
}

function titled(slide, text) {
  slide.addText(text, { placeholder: "title" });
}

// ---------------------------------------------------------------- 1. 表紙
{
  const slide = pres.addSlide({ masterName: "TITLE_DARK" });
  label(slide, "表紙の題", "single-gpu-local-ai", 0.7, 1.0, 8.6, 1.0, { fontSize: 44, bold: true, color: C.background1, valign: "middle" });
  label(slide, "表紙の副題", "24 GB の GPU 1 枚で、\nローカル AI の群れを運用し、測る", 0.7, 2.1, 8.6, 1.1, {
    fontSize: 24, color: C.background2, valign: "top",
  });
  // 1 本の VRAM を取り合う、という図案。幅は取り合いの表現で、使用量の縮尺ではない。
  const names = ["Ollama", "Strata", "Pixal3D", "Hunyuan3D", "ComfyUI"];
  const fills = [C.accent1, C.accent5, C.accent3, C.accent4, C.accent6];
  const segmentWidth = 8.6 / names.length;
  names.forEach((name, index) => {
    box(slide, `表紙の帯 ${name}`, name, 0.7 + segmentWidth * index, 3.55, segmentWidth - 0.08, 0.6, fills[index], C.background1, 14);
  });
  label(slide, "表紙の説明", "資源の排他・モデルの測定・クラウドとの連携を設計した、個人プロジェクト", 0.7, 4.35, 8.6, 0.7, {
    fontSize: 14, color: C.accent2,
  });
  slide.addNotes("single-gpu-local-ai の紹介。GPU 1 枚（NVIDIA A30 24 GB）で LLM・3D 生成・画像ワークフローを運用し、モデルを測り、クラウドの AI と連携する。");
}

// ---------------------------------------------------------------- 2. 解いた問題
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "解いた 4 つの問題");
  const items = [
    ["1", "1 枚の GPU を取り合う", "Qwen 27B だけで VRAM 22 GiB。ほかのサービスは同時に載らない"],
    ["2", "RAM が尽きると落ちる", "低 VRAM モードが RAM を使い切り、デスクトップごと停止した"],
    ["3", "感覚でなく、測る", "9 つの AI を、同じ 16 問・同じ採点で比べる"],
    ["4", "クラウドから回す", "機械的な実装の反復だけを、ローカルの Qwen へ渡す"],
  ];
  items.forEach(([number, heading, body], index) => {
    const x = index % 2 === 0 ? 0.5 : 5.15;
    const y = index < 2 ? 1.35 : 3.3;
    card(slide, `問題 ${number} の枠`, x, y, 4.35, 1.75);
    numberDot(slide, `問題 ${number} の番号`, number, x + 0.25, y + 0.3, 0.6);
    label(slide, `問題 ${number} の見出し`, heading, x + 1.1, y + 0.25, 3.0, 0.4, { fontSize: 16, bold: true, color: C.text2 });
    label(slide, `問題 ${number} の説明`, body, x + 1.1, y + 0.75, 3.05, 0.85);
  });
  slide.addNotes("出典: knowledge/10-silver/areas/env.md（VRAM 22,201 MiB）、knowledge/10-silver/resources/service-memory-limits.md（RAM の枯渇）、tools/model-eval（9 つの AI・16 問）。");
}

// ---------------------------------------------------------------- 3. 全体の構成
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "全体の構成");
  const bright = C.background1;
  // 行 1: クラウドの AI → 連携層 → Ollama
  box(slide, "利用側 Claude Code", "Claude Code / Codex", 0.5, 1.2, 2.2, 0.7, C.accent3, bright, 13);
  box(slide, "連携層", "local-ai-bridge / qwen-worker（MCP）", 3.3, 1.2, 2.5, 0.7, C.accent6, bright, 12);
  arrow(slide, "矢印 Claude から連携層", 2.7, 1.55, 0.6, 0);
  // 行 2: ブラウザ → 入口ページ → サービス群
  box(slide, "利用側 ブラウザ", "ブラウザ", 0.5, 2.6, 2.2, 0.7, C.accent3, bright, 13);
  box(slide, "入口ページ", "入口ページ portal :8080", 3.3, 2.6, 2.5, 0.7, C.accent1, bright, 13);
  arrow(slide, "矢印 ブラウザから入口ページ", 2.7, 2.95, 0.6, 0);

  const services = [
    ["Ollama :11434（Qwen3.8-27B）", C.accent1],
    ["Strata :8082〜8084（MoE 推論）", C.accent5],
    ["Pixal3D :7861", C.accent5],
    ["Hunyuan3D :7860", C.accent5],
    ["ComfyUI :8188", C.accent5],
  ];
  services.forEach(([text, fillColor], index) => {
    const y = 1.2 + index * 0.54;
    box(slide, `サービス ${index + 1}`, text, 6.5, y, 3.0, 0.46, fillColor, bright, 12);
  });
  arrow(slide, "矢印 連携層から Ollama", 5.8, 1.55, 0.7, 0);
  // 入口ページ → 4 つの GPU サービス（括弧）
  slide.addShape(S.LINE, { x: 6.25, y: 2.0, w: 0, h: 1.62, line: { color: C.accent6, width: 1.5 }, objectName: "括弧の縦線" });
  arrow(slide, "矢印 入口ページから括弧", 5.8, 2.95, 0.45, 0);
  [2.0, 2.54, 3.08, 3.62].forEach((centerY, index) => {
    arrow(slide, `矢印 括弧からサービス ${index + 2}`, 6.25, centerY, 0.25, 0);
  });
  label(slide, "構成の注記", "入口ページは、起動の前に他の GPU サービスを止め、Strata の前には Ollama のモデルも降ろす", 0.5, 3.95, 9.0, 0.35, {
    fontSize: 12, color: C.accent6,
  });
  box(slide, "GPU 帯", "NVIDIA A30 24 GB（1 枚）— 同時に載せられる GPU サービスは 1 つ", 0.5, 4.4, 9.0, 0.55, HEX.dk2, bright, 14);
  slide.addNotes("出典: docs/architecture.md、tools/portal/portal.py の GPU_EXCLUSIVE_KEYS と OLLAMA_UNLOAD_BEFORE_START_KEYS。");
}

// ---------------------------------------------------------------- 4. GPU の排他
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "GPU の排他は 2 層で守る");
  const columns = [
    ["入口ページ（portal）", ["起動の前に、動いている他の GPU サービスを止める", "Strata の起動前に Ollama のモデルを降ろす", "停止に失敗したら、起動しない"]],
    ["systemd（Conflicts=）", ["Strata 3 種は互いを止める", "After= は片側だけに書く（両側は順序が輪になる）", "systemctl を直に叩く操作も守る"]],
  ];
  columns.forEach(([heading, lines], index) => {
    const x = index === 0 ? 0.5 : 5.15;
    card(slide, `層 ${index + 1} の枠`, x, 1.3, 4.35, 2.35);
    label(slide, `層 ${index + 1} の見出し`, heading, x + 0.25, 1.45, 3.85, 0.4, { fontSize: 16, bold: true, color: C.text2 });
    slide.addText(
      lines.map((line, lineIndex) => ({ text: line, options: { bullet: true, breakLine: lineIndex < lines.length - 1 } })),
      { x: x + 0.25, y: 1.95, w: 3.85, h: 1.6, fontSize: 14, color: C.text1, valign: "top", margin: 0, paraSpaceAfter: 6, isTextBox: true, objectName: `層 ${index + 1} の本文` },
    );
  });
  // 起動の所要時間
  label(slide, "起動時間の数字 冷", "250 秒", 0.5, 3.85, 2.2, 0.7, { fontSize: 40, bold: true, color: C.accent4, valign: "middle" });
  label(slide, "起動時間の説明 冷", "冷えた状態での起動（Pixal3D）", 0.5, 4.55, 2.8, 0.5, { fontSize: 12, color: C.accent6 });
  label(slide, "起動時間の数字 温", "約 80 秒", 3.4, 3.85, 2.4, 0.7, { fontSize: 40, bold: true, color: C.accent1, valign: "middle" });
  label(slide, "起動時間の説明 温", "キャッシュが温まっている状態", 3.4, 4.55, 2.6, 0.5, { fontSize: 12, color: C.accent6 });
  label(slide, "起動の判定", "起動の完了は「ポートが開いたか」で判定する。systemd が active でも、モデルの読み込み中はポートが閉じている", 6.2, 3.85, 3.3, 1.2, { fontSize: 13, color: C.text1 });
  slide.addNotes("出典: knowledge/10-silver/resources/gpu-exclusive-switching.md（2026-09-27 実測）、CLAUDE.md（Conflicts= と After=）。");
}

// ---------------------------------------------------------------- 5. コンテキスト長と VRAM
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "コンテキスト長の上限は 65,536");
  slide.addChart(
    pres.charts.BAR,
    [{ name: "VRAM（MiB）", labels: ["32,768", "65,536", "81,920", "131,072", "262,144"], values: [19987, 22201, 22569, 22533, 22497] }],
    {
      x: 0.5, y: 1.25, w: 5.9, h: 3.8, barDir: "col", chartColors: [HEX.accent1],
      showTitle: true, title: "Qwen3.8-27B（Q4_K_M）の VRAM（MiB）", titleFontSize: 13, titleColor: HEX.dk2, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelFontFace: "+mn-lt", dataLabelColor: HEX.dk1,
      catAxisLabelFontSize: 11, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: HEX.dk1,
      valAxisLabelFontSize: 10, valAxisLabelFontFace: "+mn-lt", valAxisLabelColor: HEX.accent6,
      valAxisMinVal: 0, valAxisMaxVal: 26000, valGridLine: { color: "DCDFE3", size: 0.5 }, catGridLine: { style: "none" },
      showLegend: false, barGapWidthPct: 60,
    },
  );
  label(slide, "上限の数字", "65,536", 6.7, 1.4, 2.8, 0.8, { fontSize: 40, bold: true, color: C.accent1, valign: "middle" });
  label(slide, "上限の説明", "100% GPU で載る最大のコンテキスト長。VRAM 22,201 MiB・生成 23〜26 tok/s", 6.7, 2.25, 2.8, 1.1, { fontSize: 14 });
  label(slide, "超過の説明", "超えると KV キャッシュが CPU へ溢れる（81,920 で CPU 9% / GPU 91%）。VRAM に余裕があるように見えても、載せるのをやめている", 6.7, 3.4, 2.8, 1.6, {
    fontSize: 13, color: C.accent6,
  });
  slide.addNotes("出典: knowledge/10-silver/archive/setup-inference.md（nvidia-smi の実測。総量 24,576 MiB）。判定は ollama ps の PROCESSOR 列。");
}

// ---------------------------------------------------------------- 6. 評価ハーネス
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "測る道具（評価ハーネス）");
  const steps = [
    ["出題", "3 種・16 問"],
    ["実行", "9 つの AI"],
    ["採点", "隠しテストを sandbox で実行"],
    ["記録", "JSON を全件保存"],
    ["レポート", "HTML を生成"],
  ];
  steps.forEach(([heading, body], index) => {
    const x = 0.5 + index * 1.85;
    card(slide, `工程 ${index + 1} の枠`, x, 1.35, 1.6, 1.45);
    label(slide, `工程 ${index + 1} の見出し`, heading, x + 0.12, 1.45, 1.36, 0.4, { fontSize: 16, bold: true, color: C.text2, align: "center" });
    label(slide, `工程 ${index + 1} の説明`, body, x + 0.12, 1.9, 1.36, 0.85, { fontSize: 12, align: "center" });
    if (index < steps.length - 1) arrow(slide, `工程 ${index + 1} の矢印`, x + 1.6, 2.07, 0.25, 0);
  });
  const points = [
    ["標準ライブラリだけ", "venv を作らず、どの機体でも同じに動く"],
    ["原文と照合する", "解説書の本文は問題の原文と照合し、食い違えば止まる"],
    ["生成物にする", "レポートは記録から生成し、手で書き換えない"],
  ];
  points.forEach(([heading, body], index) => {
    const x = 0.5 + index * 3.1;
    card(slide, `要点 ${index + 1} の枠`, x, 3.2, 2.85, 1.75);
    label(slide, `要点 ${index + 1} の見出し`, heading, x + 0.2, 3.35, 2.45, 0.4, { fontSize: 16, bold: true, color: C.accent1 });
    label(slide, `要点 ${index + 1} の説明`, body, x + 0.2, 3.85, 2.45, 1.0, { fontSize: 14 });
  });
  slide.addNotes("出典: tools/model-eval/README.md。比べたのは Claude 2・Ollama 5・Strata 3 のうち、成績が低いとして外した 1 つを除く 9 つ。");
}

// ---------------------------------------------------------------- 7. コーディングの結果
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "コーディング 6 問の結果");
  const rows = [
    ["Sonnet 5.5 xHigh", 100, HEX.accent3],
    ["Opus 5.5 xHigh", 100, HEX.accent3],
    ["gemma4:31b-it-qat", 92, HEX.accent1],
    ["Strata 公式 IQ3_XXS", 84, HEX.accent5],
    ["qwen3.8:27b", 83, HEX.accent1],
    ["gemma4:31b-ctx32k", 79, HEX.accent1],
    ["Strata Coder IQ1_M", 59, HEX.accent5],
    ["qwen3.8-flash-next IQ4_XS", 57, HEX.accent1],
    ["gemma4:e4b", 52, HEX.accent1],
  ];
  slide.addChart(
    pres.charts.BAR,
    [{ name: "能力（%）", labels: rows.map((row) => row[0]), values: rows.map((row) => row[1]) }],
    {
      x: 0.5, y: 1.2, w: 6.2, h: 3.9, barDir: "bar", chartColors: rows.map((row) => row[2]),
      showTitle: false, showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelFontFace: "+mn-lt",
      dataLabelColor: HEX.dk1, dataLabelFormatCode: '0"%"',
      catAxisLabelFontSize: 11, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: HEX.dk1, catAxisOrientation: "maxMin",
      valAxisLabelFontSize: 10, valAxisLabelFontFace: "+mn-lt", valAxisLabelColor: HEX.accent6,
      valAxisMinVal: 0, valAxisMaxVal: 110, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
      showLegend: false, barGapWidthPct: 45,
    },
  );
    label(slide, "結果の見出し", "Claude は全問合格", 7.0, 1.35, 2.5, 0.5, { fontSize: 18, bold: true, color: C.text2 });
  label(slide, "結果の説明", "能力では差がつかない（天井効果）。測れた差は速さだけ", 7.0, 1.95, 2.5, 1.1, { fontSize: 14 });
  label(slide, "結果の注意", "試行は問ごとに 1 回。サンプリングありなので、小さな差は誤差の範囲", 7.0, 3.2, 2.5, 1.0, { fontSize: 13, color: C.accent6 });
  label(slide, "凡例", "色: 青 = Claude ・ 緑 = Ollama ・ 紫 = Strata", 7.0, 4.4, 2.5, 0.6, { fontSize: 11, color: C.accent6 });
  slide.addNotes("出典: tools/model-eval/results/2026-10-08/summary.json（suites.coding.models の ability）。除外した 1 つは Strata 汎用版（RVN）。");
}

// ---------------------------------------------------------------- 8. 疑った設定が点を支えていた
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "疑った設定が、点を支えていた");
  slide.addChart(
    pres.charts.BAR,
    [
      { name: "基準（思考の上限 24,576）", labels: ["Coder IQ1_M", "公式 IQ3_XXS"], values: [62, 69] },
      { name: "上限なし", labels: ["Coder IQ1_M", "公式 IQ3_XXS"], values: [19, 0] },
      { name: "low・上限なし", labels: ["Coder IQ1_M", "公式 IQ3_XXS"], values: [10, 41] },
    ],
    {
      x: 0.5, y: 1.2, w: 5.7, h: 3.9, barDir: "col", barGrouping: "clustered", chartColors: [HEX.accent1, HEX.accent4, HEX.accent6],
      showTitle: true, title: "C4・C5 の平均点（%）", titleFontSize: 13, titleColor: HEX.dk2, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelFontFace: "+mn-lt", dataLabelColor: HEX.dk1,
      catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: HEX.dk1,
      valAxisLabelFontSize: 10, valAxisLabelFontFace: "+mn-lt", valAxisLabelColor: HEX.accent6,
      valAxisMinVal: 0, valAxisMaxVal: 100, valGridLine: { color: "DCDFE3", size: 0.5 }, catGridLine: { style: "none" },
      showLegend: true, legendPos: "b", legendFontSize: 10, legendFontFace: "+mn-lt", legendColor: HEX.dk1, barGapWidthPct: 70,
    },
  );
  slide.addText(
    [
      { text: "上限を外すと、公式版は 6 回とも答えが出なかった", options: { bullet: true, breakLine: true } },
      { text: "49 本のうち 45 本で、思考が上限に届いて打ち切られていた", options: { bullet: true, breakLine: true } },
      { text: "設定の誤りは見つからず、低い点は強い量子化で思考を終えられないことによる（意見）", options: { bullet: true } },
    ],
    { x: 6.5, y: 1.35, w: 3.0, h: 3.6, fontSize: 14, color: C.text1, valign: "top", margin: 0, paraSpaceAfter: 10, isTextBox: true, objectName: "調査の要点" },
  );
  slide.addNotes("出典: Documents/Strata_コーディング性能の調査_2026-10-09.html（思考の強さ・思考の上限・問題文の言語を条件として振った。記録は tools/model-eval/results/2026-10-09-fix）。");
}

// ---------------------------------------------------------------- 9. 委譲の費用
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "委譲しても、費用は減らなかった");
  const stats = ["0.81〜1.15", "0.88", "2.85"];
  stats.forEach((value, index) => {
    const x = 0.5 + index * 3.1;
    card(slide, `比 ${index + 1} の枠`, x, 1.3, 2.85, 1.45);
    label(slide, `比 ${index + 1} の数字`, value, x + 0.15, 1.45, 2.55, 0.75, { fontSize: 36, bold: true, color: index === 2 ? C.accent4 : C.accent1, align: "center", valign: "middle" });
    label(slide, `比 ${index + 1} の説明`, "費用の比（委譲 ÷ 単独）", x + 0.15, 2.25, 2.55, 0.4, { fontSize: 12, color: C.accent6, align: "center" });
  });
  label(slide, "費用の事実", "5 回の実測（単独は Sonnet サブエージェントの場合を含む）で、50% 以下は観測しなかった。費用はほぼ「親のターン数 × 文脈長」で、委譲は親のターンを減らせない", 0.5, 2.95, 9.0, 0.8, { fontSize: 14 });
  label(slide, "役割の見出し", "だから、役割を絞った", 0.5, 3.8, 4.0, 0.4, { fontSize: 16, bold: true, color: C.text2 });
  [["夜間のバッチ", "別のモデルによるレビュー"], ["ローカルに閉じた作業", "ほかの PC からの利用"]].forEach((lines, index) => {
    slide.addText(
      lines.map((line, lineIndex) => ({ text: line, options: { bullet: true, breakLine: lineIndex < lines.length - 1 } })),
      { x: 0.5 + index * 4.5, y: 4.3, w: 4.2, h: 0.75, fontSize: 14, color: C.text1, valign: "top", margin: 0, paraSpaceAfter: 4, isTextBox: true, objectName: `役割の一覧 ${index + 1}` },
    );
  });
  slide.addNotes("出典: knowledge/10-silver/areas/local-ai-tools.md。「round 1〜5 の実測で 委譲/単独（または Sonnet サブ）の比は 0.81〜1.15、0.88、2.85。50% 以下は未観測」。");
}

// ---------------------------------------------------------------- 10. ライセンスと再現性
{
  const slide = pres.addSlide({ masterName: "CONTENT" });
  titled(slide, "公開できるものを見極める");
  const columns = [
    ["取り込まない", ["上流はコミット固定で取得する", "モデルの重みは再配布しない", "各ライセンスを NOTICE に一覧"]],
    ["公開しない", ["Hunyuan3D のパッチ（許諾が EU・UK・韓国を対象外とする）", "出所の不明な入力画像", "保存した第三者のページ"]],
    ["再現できる", ["非対話・冪等・sudo なしの導入", "clone 先に依らない systemd 雛形", "GPU 不要の試験 1,000 件超"]],
  ];
  columns.forEach(([heading, lines], index) => {
    const x = 0.5 + index * 3.1;
    card(slide, `列 ${index + 1} の枠`, x, 1.3, 2.85, 3.0);
    label(slide, `列 ${index + 1} の見出し`, heading, x + 0.2, 1.45, 2.45, 0.4, { fontSize: 16, bold: true, color: C.accent1 });
    slide.addText(
      lines.map((line, lineIndex) => ({ text: line, options: { bullet: true, breakLine: lineIndex < lines.length - 1 } })),
      { x: x + 0.2, y: 2.0, w: 2.5, h: 2.2, fontSize: 14, color: C.text1, valign: "top", margin: 0, paraSpaceAfter: 8, isTextBox: true, objectName: `列 ${index + 1} の本文` },
    );
  });
  slide.addNotes("出典: NOTICE.md、tools/hunyuan3d/README.md（ライセンスの地域制限）、scripts/lib/render-unit.sh。試験の件数は ./localai test の結果（2026-10-13 時点で 1,090 件）。");
}

// ---------------------------------------------------------------- 11. まとめ
{
  const slide = pres.addSlide({ masterName: "CLOSING_DARK" });
  titled(slide, "学んだことと、次にやること");
  label(slide, "学んだこと", "学んだこと", 0.5, 1.35, 4.3, 0.4, { fontSize: 16, bold: true, color: C.accent2 });
  slide.addText(
    ["取り合いは「誰が止める責任を持つか」を 1 か所に決める", "数字の前に、条件のそろい方を疑う", "測った値と意見を分けて書く"].map((line, index, all) => ({
      text: line, options: { bullet: true, breakLine: index < all.length - 1 },
    })),
    { x: 0.5, y: 1.85, w: 4.3, h: 2.0, fontSize: 14, color: C.background1, valign: "top", margin: 0, paraSpaceAfter: 8, isTextBox: true, objectName: "学んだことの一覧" },
  );
  label(slide, "次にやること", "次にやること", 5.2, 1.35, 4.3, 0.4, { fontSize: 16, bold: true, color: C.accent2 });
  slide.addText(
    ["評価の試行回数を増やす", "A30 以外の GPU での導入確認", "入口ページの認証"].map((line, index, all) => ({
      text: line, options: { bullet: true, breakLine: index < all.length - 1 },
    })),
    { x: 5.2, y: 1.85, w: 4.3, h: 2.0, fontSize: 14, color: C.background1, valign: "top", margin: 0, paraSpaceAfter: 8, isTextBox: true, objectName: "次にやることの一覧" },
  );
  label(slide, "リポジトリの URL", REPO_LABEL, 0.5, 4.15, 9.0, 0.4, { fontSize: 18, bold: true, color: C.background1 });
  label(slide, "Pages の URL", `評価レポート: https://${PAGES_LABEL}/`, 0.5, 4.6, 9.0, 0.35, { fontSize: 14, color: C.background2 });
  slide.addNotes("コードと文書と計測の記録はすべてリポジトリにある。ライセンスは MIT。上流とモデルの重みは再配布しない（NOTICE.md）。");
}

// ---------------------------------------------------------------- 書き出し
(async () => {
  await pres.writeFile({ fileName: OUT_PATH });
  const applyThemePath = process.env.PPTX_APPLY_THEME;
  if (applyThemePath) {
    const { applyTheme } = require(applyThemePath);
    await applyTheme(OUT_PATH, THEME);
    console.log("theme applied");
  } else {
    console.warn("PPTX_APPLY_THEME が未指定: テーマの色は Office の既定のままです");
  }
  console.log("wrote", OUT_PATH);
})();
