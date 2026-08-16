# ADR-0009: OpenHandsへの委譲範囲とSkill化方針

> ステータス: Accepted
> 日付: 2026-08-16
> 関連: [`../../README.md`](../../README.md)、[`../../AGENTS.md`](../../AGENTS.md)、[`../openhands-integration.md`](../openhands-integration.md)、[`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)、[`ADR-0008-minimal-vibebb-scope.md`](ADR-0008-minimal-vibebb-scope.md)

## コンテキスト

ADR-0008でVibeBBの最小構成へ絞ったあとも、ACD本体には「OpenHandsの標準能力（shell、
ファイル編集、テスト実行、subagent、vision）で足りる処理」が残っていた。具体的には
ESP-IDF向けFWのビルド・検査、決定論的な配置・回転探索、シルクラベルの探索、代理指標の
採点である。これらはいずれも設計の合否を決める処理ではなく、候補を作るための探索と、
通常のソフトウェア開発作業である。

一方で、これらの実装は実際に動いた資産であり、単純に削除すると再利用できない。過去の
見直しで削除した品質管理・信頼性の作業手法（QC7つ道具、Q7/N7など）も同じ性質を持つ。

ACDが手放せないのは、入力ファイルの読み取り、投影、生成経路とは別parserによる独立再読込、
ERC/DRC・機械ゲート、発注ガードである。誤りが実物と金額で返るのはこの範囲だけである。

## 決定

### 1. ACD本体は軽量に保つ

ACD本体が保持する実装は、投影、決定論的ゲート、パイプラインスクリプト、adapters、
発注ガード、`profiles/`の宣言、OpenHands plugin資材に限る。探索、採点、FW検査、
品質管理手法はACD本体に持たない。

### 2. 委譲した資産はSkillとして提供する

委譲した処理は削除ではなく`plugins/acd/skills/<name>/`へ移す。各Skillは`SKILL.md`（用途、
呼び出し方、外部ツール要件、ツール不在時の挙動、限界、ACDゲートではない旨）と、必要な
`scripts/`、`tests/`を持つ。

### 3. Skillの採否はOpenHands側が判断する

Skillは任意利用の資産である。ACD本体のパイプラインが常に呼ぶ前提を置かず、タスクの性質と
有用性に応じてOpenHands側が採否を判断する。Skillが存在することは採用の義務を意味しない。

### 4. Skillの実行結果はACDの設計ゲートの合否ではない

代理指標のスコア、Skill内の検査、QEMUなどの仮想実行結果は候補の順位付けと開発時の確認に
使う。合否はERC/DRC、機械ゲート、独立再読込、発注ガードだけが決める。仮想実行の結果は
実機のEvidenceを置き換えない。

### 5. FW検査はACDゲートから外す

FWのビルド、静的解析、単体テスト、ピン割当整合、ログ期待値照合はOpenHands側（Skillおよび
通常のテスト）の責務とする。ACD本体はFWゲートを持たない。既存のESP-IDF実装は
`acd-firmware-esp32c3` Skillとして提供する。

### 6. 探索と採点はSkillへ移す

配置・回転探索、シルクラベル探索、代理指標の採点はSkillへ移す。LLMが座標・回転角を直接
提案してもよい。提案は候補にとどまり、設計の入力ファイルへ確定したのちにACDの投影と
決定論的ゲートで判定する。

### 7. Skillのテストは本体テストと分離する

Skillのテストは`plugins/acd/skills/<name>/tests/`に置き、`uv run pytest plugins -q`で
実行する。CIでも本体の`verify`ジョブとは別ジョブで実行する。外部ツール（ESP-IDF、QEMUなど）を
要するテストはツール不在時にskipしてよい。Skillテストの合否はACDの設計ゲートの合否とは
別に扱う。

### 8. ACD本体への再実装は実運用で不足を確認してから行う

OpenHands側の機能で不足するとVibeBBの実運用で確認できた場合に限り、ACD本体への実装を
検討する。想定だけで本体へ機能を戻さない。

## 検討した代替案

| 代替案 | 却下理由 |
|---|---|
| 探索器・FW検査をACD本体に残す | 合否を決めない処理が本体の保守対象として増え続ける。OpenHandsの標準能力と二重になる |
| 委譲対象のコードを削除する | 実際に動いた資産を再利用できなくなる。SkillにすればOpenHands側が必要時に使える |
| Skillをパイプラインから必ず呼ぶ | 採否の判断をOpenHands側に置く方針と矛盾し、案件ごとに別の探索法を選べなくなる |
| Skillのテストを本体テストへ統合する | 外部ツール依存でCIが不安定になり、Skillの合否と設計ゲートの合否が混ざる |
| 探索スクリプトを設計プロジェクト側だけに置く | 再利用されず、同じ実装が案件ごとに書き直される |

## 影響

- [`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)の
  「LLMに座標・回転角を直接出力させない」は撤回する。三層分離の考え方と、代理指標を
  合格根拠にしないことは維持する。
- [`ADR-0008-minimal-vibebb-scope.md`](ADR-0008-minimal-vibebb-scope.md)の§8のうち、
  ピン割当整合を生成スクリプト内の検査として残す部分は撤回し、FW検査は全てOpenHandsへ委譲する。
- `packages/adapters/acd-adapter-espidf`とFWパッケージ契約は削除し、`acd-firmware-esp32c3`
  Skillへ移した。配置探索・採点は`acd-placement-search`、シルクラベル探索は
  `acd-silkscreen-placement`へ移した。
- CI（`.github/workflows/ci.yml`）にSkill専用ジョブを追加した。
- 過去に削除した品質管理・信頼性の作業手法は、必要なものをSkillとして再構成する。

## 未確認・リスク

- 探索をSkillへ移したことによる収束性・実行時間の変化はGD1でしか確認していない。
- Skillの採否をOpenHands側の判断に委ねるため、同じ設計が毎回同じ手順で作られる保証はない。
  再現性はゲート出力とgitのcommitで担保する。
- Skillテストは本体ゲートと分離したため、Skillの劣化が設計ゲートの失敗として表面化しない。
