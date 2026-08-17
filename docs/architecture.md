# アーキテクチャ

> ステータス: Draft
> 対象: OpenHands Software Agent SDK v1.42.1、Python 3.12+

本書は、入力ファイルを正とするACDの実装境界を定める。実行基盤の統合面は
[`openhands-integration.md`](openhands-integration.md)、工程は
[`design-flow.md`](design-flow.md)、設計決定は[`adr/`](adr)を参照する。

## 正規データと責務境界

設計グラフとプロファイルはPydantic契約で検証する入力ファイルであり、git commitと
ともに設計の正である。KiCad project、Gerber/drill、BOM/CPL、STEP/3MF、evidenceは
入力から生成する派生投影であり、投影結果を入力へ逆流させない。

```text
入力ファイル / profiles
        ↓
acd-schema（Pydantic契約）
        ↓
acd-core（電気・機械・fab意図の抽出と共通モデル）
        ↓
acd-pipeline（GD1基板・筐体の決定論的投影とゲート）
        ↓
adapters/*（KiCad、FreeRouting、CAD）
        ↓
生成物、独立再読込、evidence
```

AIとSkillは探索・実装・所見を提案する。合否はACDの決定論的ゲートだけが判定する。
ツール不在、入力不備、parse失敗、未実行、unknown、未検証はfail-closedとする。

## Pythonパッケージ

```text
packages/
├── acd-schema/       # DesignGraph、Evidence、ToolEnvelope等の契約
├── acd-core/         # 電気・機械・fab意図の抽出と共通モデル
├── acd-pipeline/     # GD1 board/enclosure pipeline
├── acd-tools/        # 外部ツールprobeとFastMCP server
└── adapters/
    ├── acd-adapter-kicad
    ├── acd-adapter-freerouting
    └── acd-adapter-cad
```

`acd-schema`は契約の正であり、`acd-core`は外部ツール固有の判定を持たない。
`acd-pipeline`は入力を投影し、ERC/DRC、routing収束、独立再読込、Gerber/機械測定などの
ゲートを実行する。adaptersは外部ツールとの形式・process境界を担当し、設計の合否を
独自に決めない。`acd-tools`のMCP toolは既存の決定論的入口を公開するだけである。

## OpenHands plugin

```text
plugins/acd/
├── .plugin/plugin.json
├── .mcp.json
├── commands/gates.md
├── agents/
│   ├── acd-electrical.md
│   ├── acd-mechanical.md
│   ├── acd-firmware.md
│   └── acd-reviewer.md
└── skills/
    ├── acd-contracts/
    ├── acd-placement-search/
    ├── acd-silkscreen-placement/
    ├── acd-firmware-esp32c3/
    ├── acd-cad-determinism-probe/
    ├── acd-qc-seven-tools/
    └── acd-reliability-review/
```

pluginはOpenHands SDKが読むMarkdown、manifest、MCP設定の配布単位であり、ACD Python
moduleをSkill本文からimportする経路ではない。配置・シルク探索の実行資材はSkillの
CLIをsubprocessから呼び、結果をgraph.jsonの設計入力へ確定する。Skill名とscript
sha256をprovenanceへ記録し、欠落・不一致は停止する。

Skillの`triggers`はSDKの`KeywordTrigger`を使う。`paths:`は
`disable_model_invocation=True`を強制し、`inputs:`はTaskTriggerになるため、現在の
自然言語起点の任意利用には採用しない。Skill結果、AgentDefinitionの所見、reviewerの
出力は合否Evidenceではない。

## MCP境界

`packages/acd-tools/src/acd_tools/mcp_server.py`はFastMCP stdio serverとして、次の
既存入口だけを公開する。

- `probe_tools`
- `validate_design_graph(path)`
- `run_board_pipeline(fixture, out, fab_profile, max_passes)`
- `run_enclosure_pipeline(fixture, out)`

MCPは読み取り、契約検証、既存pipeline実行の入口であり、設計権威や新しいゲート、
閾値、期待値を持たない。返り値はstatus、失敗理由、出力パス、summary、可能な
ToolEnvelope情報を含む構造化JSONで、入力不備や例外はfail-closedとなる。

## 生成と判定の分離

配置、回転、シルク候補、FW作業、QC・信頼性レビューはOpenHands Skillまたはagentが
提案・実行する。ACDは候補を入力ファイルへ確定した後、投影と決定論的ゲートを行う。
ゲートは生成後の成果物を独立parser・測定器で確認し、Skillの代理指標や自然文を
合格根拠にしない。

GD1では、基板pipelineがERC、routing収束、SES import、DRC、fabrication出力、独立再読込
まで進む一方、silkscreen可読性ゲートは既知のgeometry判定不一致によりfail-closedで
停止する。この既知課題の条件差と解決方向は
[`adr/ADR-0011-search-results-as-design-input.md`](adr/ADR-0011-search-results-as-design-input.md)
に記録する。筐体pipelineは決定論的CADゲートを通過する。

## 実装していない境界

SecretRegistry連携、DockerWorkspace実行、agent-server運用、Conversationを使った
実行経路、実機測定、価格・在庫取得、自働発注は未実装であり、将来構想である。

## hook境界

`plugins/acd/hooks/`はSDKのhook契約を使い、agent経路だけで安全境界を追加する。
派生投影（`out/`、`evidence/`、製造出力）への直接書き込み、ゲート未通過の発注・
外部送信、設計入力変更後の未検証終了をdenyする。保護部分木に触れていない操作は
停止させず、保護対象への言及を読み取り専用と確定できない場合はfail-closedにする。
hookは既存のPydantic契約と決定論的ゲートを呼ぶだけで、新しい閾値を持たない。
SDK hookのDENYはagent経路にしか効かないため、CI側の検証も二重に保持する。

発注・外部送信のorderガードは、(1) transmission commandがリポジトリ内の`out/`または
policyのartifact globに一致する製造成果物に触れる、または(2)明示的なorder command
である場合だけEvidenceを要求する。コマンドは実行ファイルのtoken単位で検出し、
URLは成果物として扱わないため、通常の`git push`、文書取得の`curl`、供給者データの
取得は対象外である。policyのEvidence globで解決した各ファイルをCLIへ複数渡し、
`required_evidence_ids`の各IDについて現revisionに一致する`supports_pass()`が必要である。
GD1基板pipelineは現状Evidenceレコードを生成しないため、基板fabrication成果物の送信は
fail-closedになる。

Stopガードはorderガードより弱く、order policyのEvidence globで解決したファイルのうち、
dirtyな設計入力より新しいmtimeのvalidかつunknownなしEvidenceが存在する場合に限り
終了を許可する。mtimeの新しさはpass Evidenceではなく、`--valid-only`はStopガード専用
の新しさ確認である。`supports_pass()`は引き続きcommit済みrevision一致を要求する。
該当しない場合は原因となった設計入力パスをreasonに列挙する。

これらを現行ACDの採用済み機能や合否根拠として扱わない。
