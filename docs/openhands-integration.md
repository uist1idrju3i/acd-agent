# OpenHands統合

> ステータス: 実装済み範囲と未実装範囲を分離して記録
> 対象: OpenHands Software Agent SDK v1.42.1

## 統合方針

ACD pluginをOpenHands側の主成果物とする。OpenHandsはSkill、AgentDefinition、
command、MCP設定、workspace実行を提供し、Python側はPydantic契約、決定論的投影、
ゲート、adapter、evidence契約を保持する。AIやSkillの出力は候補・所見であり、
ACDの合否根拠ではない。

SDKは`vendor/software-agent-sdk`のv1.42.1を参照する。Agent Canvasのsubmoduleは使用せず、
OpenHandsの公開Skills repositoryはsubmoduleにせず外部参照とする:
<https://github.com/OpenHands/extensions>

## plugin構成

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
    ├── acd-contracts
    ├── acd-placement-search
    ├── acd-silkscreen-placement
    ├── acd-firmware-esp32c3
    ├── acd-cad-determinism-probe
    ├── acd-qc-seven-tools
    └── acd-reliability-review
```

### Skill trigger

7 Skillは`version`、`license`、`triggers`をfrontmatterに持つ。
`triggers`はSDKの`KeywordTrigger`であり、内容に即した英語キーワードを3〜6個指定する。
`paths:`は`disable_model_invocation=True`を強制するため使わない。`inputs:`は
TaskTriggerになるため、現在の自然言語起点の任意利用には適さず使わない。

Skillは作業手法と探索器を提供するが、結果は合否Evidenceではない。配置・シルク探索を
fixture生成で利用する場合も、ACD本体からSkillのPython moduleをimportせず、CLIを
subprocess実行して結果を設計入力へ確定する。scriptのsha256とSkill名をprovenanceへ
記録し、入力不備や実行失敗はfail-closedとする。

## AgentDefinition

| 定義 | 役割 | Skill | 権限 |
|---|---|---|---|
| `acd-electrical` | 回路レーン投影、配置、ERC/DRC失敗調査 | `acd-contracts`, `acd-placement-search`, `acd-silkscreen-placement` | `confirm_risky` |
| `acd-mechanical` | 筐体投影、機械ゲート、CAD決定性 | `acd-contracts`, `acd-cad-determinism-probe` | `confirm_risky` |
| `acd-firmware` | ESP32-C3のFW開発、ビルド、仮想実行 | `acd-firmware-esp32c3` | `confirm_risky` |
| `acd-reviewer` | 投影レビューと所見整理。合否権限なし | `acd-qc-seven-tools`, `acd-reliability-review` | `never_confirm` |

各定義は`model: inherit`、反復上限、budget上限を持ち、toolはSDKで確認した
`terminal`、`file_editor`、`grep`、`glob`、`task_tracker`に限定する。reviewerの
自然文所見は合否を決めず、決定論的ゲートへ戻される。

## `/acd:gates`

`.plugin/plugin.json`の`entry_command: "gates"`により、`/acd:gates`を提供する。
command本文は既存の決定論的電気・機械ゲートを実行するようagentへ指示し、閾値・
期待値・evidence規則を変更しない。ツール不在、未知状態、parse失敗、未検証は
fail-closedとする。

## ACD MCP server

`packages/acd-tools`の`acd-mcp`はFastMCP 3.4.7を使いstdioで起動する。公開範囲は
既存の読み取り・契約検証・pipeline入口だけであり、設計権威をMCPに与えない。

| tool | 内容 |
|---|---|
| `probe_tools()` | 外部ツールの有無と版を返す |
| `validate_design_graph(path)` | Pydantic契約でgraphを検証する |
| `run_board_pipeline(fixture, out, fab_profile, max_passes)` | 既存GD1基板pipelineを実行する |
| `run_enclosure_pipeline(fixture, out)` | 既存GD1筐体pipelineを実行する |

返り値は`ok`、`operation`、`failure_reason`、`fail_closed`、summary、出力パス、
ToolEnvelope由来のtool名・版・hashを含む構造化JSONである。入力不備、ファイル不在、
JSON/Pydantic parse失敗、pipeline例外は成功に見せずfail-closedで返す。

## 未実装・将来

以下はSDKに存在する概念を調査したが、本リポジトリの採用済み実行経路ではない。

- SecretRegistry連携とprovider secretの注入
- DockerWorkspace実行
- agent-serverの運用
- Conversationを使ったACD実行経路、fork、長時間resume
- SDKのcritic、goal、workflow、memoryを使う自動修復ループ
- browser経由のsourcingと自働発注

これらは将来検討であり、現行の合否・Evidence・発注契約には使わない。

## 外部参照

OpenHandsが公開する追加Skillsの参照先は
<https://github.com/OpenHands/extensions> である。クローン重量と更新負債を避けるため、
このrepositoryはこれをsubmoduleとしてvendorしない。ACD pluginのSkillとは別の外部資材
として扱う。
