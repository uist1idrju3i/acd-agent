# ACDアーキテクチャ

> ステータス: Draft

ACDは入力ファイルとgitを設計の正とし、OpenHands SDKを実行基盤として使う。ACDに残すのは
adapters、パイプラインスクリプト、`profiles/`の安全設定、決定論的ゲート、発注ガードである。
契約はPydanticモデルで表現する。

## レイヤ

```text
Pydantic models
    ↓
adapters（KiCad、Gerber、router、CAD kernel、slicer、fab）
    ↓
pipeline scripts（生成、再読込、ERC/DRC、干渉、FW検査）
    ↓
OpenHands plugin（Skill、AgentDefinition、MCP設定）
```

生成と判定を分離する。候補生成、整合化、代理指標は生成側に置き、実測とゲートは判定側に
置く。判定側は生成側の成功状態を合格根拠にせず、外部ツールや独立parserの結果だけを判定する。

## 投影とレビュー

入力ファイルから機械可読投影と視覚投影を生成する。機械可読投影はnetlist、寸法、干渉、
ピン割当、ゲート結果など、視覚投影は回路図、レイアウト、3Dビュー、断面などである。
投影は入力へ逆流させず、LLMのsubagentとvisionへ渡して次の修正を決める材料にする。
LLMレビューは自然文の所見を返すだけで、合否権限を持たない。

## ゲートと発注

合格条件はERC/DRC通過と、生成経路とは別parserによる成果物の再読込である。ツール不在、
parse失敗、ゲート未実行、安全境界の`unknown`はfail-closedで停止する。ライブラリ記述の
誤りやLLMの説明をERC/DRCの合格根拠にしない。

発注ガードは設定上限額以内であることと、発注直前に全ゲートを通過していることの2条件を
確認する。発注直前には価格・在庫の鮮度も確認する。

## 安全境界

安全境界の設定変更は`profiles/`配下の版管理されたcommitだけで行う。会話やLLM出力から
安全境界を変更しない。ACD独自の共通executorや独自tool層を設けず、不可逆操作の確認は
OpenHandsの`ConfirmationPolicy`へ委ねる。

## 関連文書

- [`design-flow.md`](design-flow.md)：工程とゲート
- [`openhands-integration.md`](openhands-integration.md)：SDKとpluginの境界
- [`projection-review.md`](projection-review.md)：2種類の投影レビュー
