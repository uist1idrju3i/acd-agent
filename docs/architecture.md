# アーキテクチャ

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1、Python 3.12+

本書は境界説明の単一の正であり、入力ファイルを正とするACDの実装境界を定める。
SDK機能の採否は[`openhands-sdk-capabilities.json`](openhands-sdk-capabilities.json)を正とし、
説明表は[`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md)に置き、
運用手順は[`operations.md`](operations.md)、ゲート仕様は[`gates.md`](gates.md)を参照する。
Accepted ADRの索引は[`README.md`](README.md)、文書統治は
[`adr/ADR-0034-document-governance.md`](adr/ADR-0034-document-governance.md)を参照する。

## 正規データと責務境界

設計グラフとプロファイルはPydantic契約で検証する入力ファイルであり、git commitと
ともに設計の正である。KiCad project、Gerber/drill、BOM/CPL、STEP/3MF、evidenceは
入力から生成する派生投影であり、投影結果を入力へ逆流させない。設計判断の理由は
typed `rationale.json`へ記録し、graphの必須属性に対するcoverageを決定論的に検査する。

```text
入力ファイル / profiles
        ↓
acd.schema（Pydantic契約）
        ↓
acd.core（電気・機械・fab意図の抽出と共通モデル）
        ↓
acd.pipeline（GD1基板・筐体の決定論的投影とゲート）
        ↓
acd.adapters.*（KiCad、FreeRouting、CAD）
        ↓
生成物、独立再読込、evidence
```

`rationale.json`はgraphと同じrevisionを対象にし、subject hash、要求、代替案、provenance
を保持する。graphに要求nodeがある場合は`driving_requirements`、文書にだけ要求がある
場合は`driving_requirement_refs`（文書パスと要求ID）を使う。stale、unknown、orphan、
conflicting、missing、untraceable、unclassifiedはfail-closedで停止する。graph属性は
必須または英語理由付き免除のどちらかに分類し、未分類属性を黙ってcoverage外へ置かない。
rationaleのMarkdownはpipeline出力の派生レビュー投影であり、canonical inputではない。

AIとSkillは探索・実装・所見を提案する。三層分離は
[`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md)に従う。L1判定は
決定論的ゲートと`Evidence.supports_pass(graph.revision)`だけが担い、L2操舵とL3観測は
合否を判定しない。L2とL3は停止側にだけ作用でき、合格側へ作用させない。
実機Evidenceは測定結果を入力更新へ渡す根拠であり、`supports_pass()`を満たしても
決定論的ゲートの合格側へ昇格しない。
ツール不在、入力不備、parse失敗、未実行、unknown、未検証はfail-closedとする。

pluginの外部配布では、`github:uist1idrju3i/acd-agent`の`plugins/acd`を40桁commit SHA
または`v<semver>` tagへ固定する。branch名や未指定refはprovenance不明として拒否する。
開発時のlocal pathはSDK Conversationの既定経路として残す。TestLLMはSDK wiringと
critic反復の回帰に使うが、metricsやcritic出力を合否Evidenceへ昇格させない。

## Pythonパッケージ

```text
src/acd/
├── schema/           # DesignGraph、Evidence、ToolEnvelope等の契約
├── core/             # 電気・機械・fab意図の抽出と共通モデル
├── pipeline/         # GD1 board/enclosure pipeline
├── openhands/
│   ├── session/      # Conversation、goal loop、gate critic
│   ├── safety/       # security、secret、hook境界
│   ├── evidence/     # evidenceとgit/revision検証
│   ├── tools/        # SDK ToolDefinitionとprobe
│   └── distribution/ # pluginとSkill配布
└── adapters/
    ├── kicad
    ├── freerouting
    └── cad
```

`acd.schema`は契約の正であり、`acd.core`は外部ツール固有の判定を持たない。
`acd.pipeline`は入力を投影し、ERC/DRC、routing収束、独立再読込、Gerber/機械測定などの
ゲートを実行する。adaptersは外部ツールとの形式・process境界を担当し、設計の合否を
独自に決めない。`acd.openhands`のSDK toolは既存の決定論的入口を公開するだけである。

## OpenHands plugin

```text
plugins/acd/
├── .plugin/plugin.json
├── hooks/
├── commands/
│   ├── gates.md
│   └── doctor.md
├── agents/
│   ├── acd-electrical.md
│   ├── acd-mechanical.md
│   ├── acd-firmware.md
│   ├── acd-reviewer.md
│   ├── acd-search.md
│   └── prompt-manifest.json
└── skills/
    ├── acd-contracts/
    ├── acd-placement-search/
    ├── acd-silkscreen-placement/
    ├── acd-firmware-esp32c3/
    ├── acd-cad-determinism-probe/
    ├── acd-qc-seven-tools/
    ├── acd-reliability-review/
    ├── acd-design-rationale/
    └── acd-install-doctor/
```

pluginはOpenHands SDKが読むMarkdown、manifest、hooksの配布単位であり、ACD Python
moduleをSkill本文からimportする経路ではない。配置・シルク探索の実行資材はSkillの
CLIをsubprocessから呼び、結果をgraph.jsonの設計入力へ確定する。Skill名とscript
sha256をprovenanceへ記録し、欠落・不一致は停止する。

`acd-install-doctor`はplugin内の標準ライブラリscriptだけでinstall経路とruntime
capabilityを観測する。これはL3観測であり、合否権限やauthoritative Evidence生成を
持たない。required checkのunknownはfail-closedであり、Docker不在時にhost実行を
合格側へ緩めない。

Skillの`triggers`はSDKの`KeywordTrigger`を使う。`paths:`は
`disable_model_invocation=True`を強制し、`inputs:`はTaskTriggerになるため、現在の
自然言語起点の任意利用には採用しない。Skill結果、AgentDefinitionの所見、reviewerの
出力は合否Evidenceではない。

role promptは`PromptSection`へ変換するL2操舵資材であり、資材bytesと抽出本文を
`prompt-manifest.json`で固定する。prompt sectionとmanifestはEvidenceではなく、
authoritative Evidenceを生成・昇格せず、決定論的ゲートの合否へ影響しない。manifest
drift、parse失敗、資材欠落はfail-closedで会話構築を停止する。

安全境界はpinned SDKへ委譲する。`AcdSecurityAnalyzer`とSDKの
`PatternSecurityAnalyzer`を`EnsembleSecurityAnalyzer(analyzers=[...])`へ合成し、
`LocalConversation.set_security_analyzer()`で設定する。確認方針は
`set_confirmation_policy(ConfirmRisky(threshold=SecurityRisk.MEDIUM))`である。
allowlist環境変数はSDK `SecretRegistry`へlazy sourceとして渡し、出力はSDKの
`mask_secrets_in_output()`でマスクする。`load_skills_from_dir()`でローカルSkillだけを
読み、`AgentContext(skills=..., load_public_skills=False, load_user_skills=False)`へ渡す。
Conversationの`stuck_detection=True`と`StuckDetectionThresholds`は停止・再試行の操舵だけに
使う。これらのL2機能と既存hooksはauthoritative Evidenceを生成せず、L1の決定論的gateを
置き換えない。
`GoalController`を再利用したACD goal loopと`LocalConversation.interrupt()`へのSIGINT結線も
L2の停止・再試行層として扱う。`ConversationStats`はL3観測に限定し、goalのjudge評決と
ともにauthoritative Evidenceの合否へ影響させない。
role別model routingは主agent、judge、condenserのbindingをpolicyへ固定し、
`RouterLLM`の選択をroleだけで決定する。policy hashとrouting観測はL2/L3資材であり、
Evidenceを生成・昇格せず、決定論的gateの合否へ影響させない。
metrics、stats、goal結果、routing観測のL3保存はSDK `FileStore`を経由する。
既存のJSON bytesと非Evidence契約を維持し、Evidenceと設計入力の保存経路は
FileStoreへ移譲しない。
lane並列は`Agent.tool_concurrency_limit`で明示的に有効化する。ACD toolの資源宣言不能時は
SDKの既定どおりtool単位のmutexで直列化する。task/delegateのsub-agentは親hookを継承
しないため、5つのACD AgentDefinitionへ同じ必須hookを明記し、SDKがロードした
`HookConfig`を決定論的に照合する。browser_useは明示有効時だけL2探索補助として登録し、
browser由来の観測をEvidenceへ昇格させない。決定論的APIがある取得経路は変更しない。
workflowは任意Python scriptがhook境界を外れるため不採用（将来再検討）とする。

## SDK ToolDefinition境界

`src/acd/openhands/tools/definitions.py`はOpenHands SDKの
`ToolDefinition`、`Action`、`Observation`、`ToolAnnotations`、`ToolExecutor`を
使い、`register_acd_tools()`から次の既存入口を明示的に登録する。

- `acd_probe_tools`
- `acd_validate_design_graph`
- `acd_run_board_pipeline`
- `acd_run_enclosure_pipeline`

返り値のキー、ToolEnvelopeの列挙、入力妥当性、fail-closed契約は旧公開方式から
不変である。MCP client互換層は提供しない。

## 生成と判定の分離

配置、回転、シルク候補、FW作業、QC・信頼性レビューはOpenHands Skillまたはagentが
提案・実行する。ACDは候補を入力ファイルへ確定した後、投影と決定論的ゲートを行う。
ゲートは生成後の成果物を独立parser・測定器で確認し、Skillの代理指標や自然文を
合格根拠にしない。

GD1では、基板pipelineがERC、routing収束、SES import、DRC、fabrication出力、独立再読込、
silkscreen可読性ゲートまで通過する。ゲートはGerber実測の幾何と判定条件をcontextとして
Skillへ配布し、Skillは自前の閾値を持たない。文字寸法の上界モデルもゲート側を単一の
出所とし、候補bboxと予約領域へcontext経由で伝える。筐体pipelineも決定論的CADゲートを
通過する。

## 期限付き見積入力境界

見積入力は外部発注ではなく、URL、取得時点、有効期限、記録時点、対象revisionを持つ
fixtureの`QuoteRecord`として保存する。金額は浮動小数ではなく、ISO 4217形式の通貨コード、
最小通貨単位桁数、非負の整数最小単位で表し、同一record内の全費目で通貨と桁数を一致させる。
費目は基板、部品、実装、送料、税を区別し、価格・在庫・納期・実装可否を区分ごとの必須
フィールドで検証する。

`read_quote()`はモデルの検証だけでは期限を判定せず、評価時刻と対象revisionを引数に取る
決定論的な読み出し関数である。出所の範囲、必須費目区分、期限、revision、`unknown`混在を
fail-closedで検査し、金額を確定値として採用するには各費目のbasisが`primary`であることを
要求する。`inference`の金額はrecordに残るが停止条件となる。返却値は費目集合とcanonical
hashだけで、Evidence、gate verdict、発注許可の権限を持たない。fixtureの取得は検証用に
限定し、実発注や外部送信は行わない。

## 総発注額の合算境界

合算前に`OrderScope`で、対象revision、fab profile、相手方区分、許可供給者、必須費目区分、
送料・税の扱い、機械部品の包含または除外理由、通貨と最小単位桁数を宣言する。宣言しない
供給者、相手方区分、fab profile、費目区分、機械部品、通貨は合算時にfail-closedで停止する。
`QuoteRecord`は供給者申告総額を持ち、費目合計との一致を契約validatorで検査する。

`aggregate_order_total()`は保存済みの見積record群へ7.1の`read_quote()`を適用し、入力順に
依存しない区分別小計、総額、各見積のcanonical hash、内訳hashを返す。期限切れや
`inference`など7.1の停止条件は再実装せず、`read_quote()`の停止をそのまま伝播する。
各recordの供給者申告総額の合計と区分別小計から算出した総額も突合し、不一致は停止する。
この合算層は金額の確定と停止だけを担い、上限額との比較、ゲート合否、Evidence、発注許可は
7.3以降の責務であり、ここでは作成しない。

## 発注前最終ゲート境界

`OrderPolicy`はhookの既存コマンド境界を保ったまま、設計graphの宣言パス、両laneの
authoritative Evidence ID、既存の発注条件、および`order_total_limit`（最小通貨単位の
整数、通貨、最小単位桁数）を厳格に宣言する。上限額の欠落、負値、`unknown`、通貨欠落、
余分なpolicy fieldは停止する。

7.2の`OrderTotalResult`をJSONへ保存・復元する場合は、`OrderTotalDocument`と
coreの変換関数を使い、集計時と復元時に同じ内訳hash定義を適用する。
OpenHands層の`evaluate_pre_order_gate()`は、SDKのgit観測で設計入力のdirty状態を確認し、
graphから解決した現行revisionと7.2の`OrderTotalResult`を照合する。電気・機械の各Evidenceは
`supports_authoritative_pass()`、revision、container digest、claimの`verified`と
`unknown`を再確認する。合算総額は上限額以下（同額を含む）でなければならない。
成功時の`PreOrderGateRecord`は既存の判定結果を集約した非Evidence recordであり、
新たなpass authority、journal書込み、外部送信、発注を作らない。

再実行は`scripts/pre_order_gate.py --rerun-authoritative`からdigest固定
`DockerWorkspace`経路を明示的に呼び出す。check-onlyは既存Evidenceだけを検査し、
現行revisionのauthoritative Evidenceがなければゲート未実行として停止する。
`LocalWorkspace`のhost provisional結果では最終ゲートを満たせない。

基板pipelineは決定論的なERC、routing、DRC、silkscreen、DFM、発注readinessの結果を
`out/gd1/evidence-electrical.json`へ記録する。筐体pipelineの
`out/gd1-enclosure/evidence-mechanical.json`と同じEvidence契約を使い、host実行では
validでもprovisionalのままとする。CIの`container-gates` jobは
`verify_authoritative_evidence.py`で両laneのrevision、status、既知provenance、
container image digestを決定論的に検査し、条件を満たさないEvidenceを合格側へ通さない。

## Docker workspace境界

digest固定コンテナだけを合格側Evidenceの実行環境とする。runnerはlockから解決した
`server_image="...@sha256:<digest>"`をSDKの`DockerWorkspace`へ渡す。host経路は
参考実行であり、provisional Evidenceだけを生成する。
repoは`volumes`でmountし、`out/`と`evidence/`をホスト側へ残す。CIとホスト実行は
参考経路であり、host実行の結果はprovisionalで合格側Evidenceへ昇格しない。
runnerは`docker image inspect`でdigestを解決し、解決できない場合はworkspaceを起動せず
fail-closedで停止する。解決したdigestと`ACD_IN_CONTAINER`をforwardし、ToolEnvelopeの
`execution_context`と`container_image_digest`へ型付きで記録する。`execution_env`は
host/architectureの説明だけに使い、container identityの判定には使わない。

CIの`container-gates` jobはlock済みserver imageをpullし、SDKの`DockerWorkspace`を使う
`scripts/run_in_workspace.py`からresolver、基板、
筐体pipelineを一つのcontainer commandとして実行する。publish workflowはmainのDockerfile
変更または手動起動でGHCRへimageをpushし、job summaryへdigestを記録する。

`Evidence.supports_pass()`はrevision、status、既知provenanceの妥当性を表す。
`supports_authoritative_pass()`はそれに加えてdigest固定containerを要求し、
hostで生成されたvalid Evidenceは`is_provisional()`として扱う。
実機Evidenceの`supports_authoritative_pass()`は常に`False`であり、実機測定結果を
authoritative Evidenceへ置き換える経路を作らない。

Dockerはdeterminismを保証しないため、timestamp、filesystem、外部ツール版、
入力・出力hashの正規化と決定論的ゲートは従来どおり必要である。ACD imageは配布せず、
利用者が[`docker/README.md`](../docker/README.md)のDockerfileを各自buildする。

## Critic境界

`AcdGateCritic`はSDKの反復制御へ接続するが、合否はDesign Graphのrevisionに
一致するEvidenceと製造manifestだけで決める。events、git patch、LLM出力は
スコアへ影響せず、critic出力はpass evidenceではない。設計入力がgitでdirty、
parse不能、stale、unknown、または要件未達なら0.0とし、全要件充足時だけ1.0とする。

## 探索並列化境界

GD1基板pipelineでは、独立したKiCad width positive-controlの2 armだけを
thread poolで並列実行できる。結果はarm-a、arm-bの固定順で集約し、並列度1は
逐次経路と同一である。worker数を変えた検証では、出力パスとKiCad DRC日時を除いた
arm summaryの正規化結果が一致し、worker例外はfail-closedで伝播する。`hashes.json`
は既存pipelineのKiCad UUIDとDRC日時による非決定性のため一致しない。この是正は
現行の決定論的探索契約の範囲外である。greedy配置探索とsilkscreen探索は状態依存の
ため並列化しない。

`acd-search` AgentDefinitionは冗長な探索出力を主会話から分離するだけで、候補と
Skill名・script SHA-256 provenanceを返す。候補、Skill、agentの出力は合否権限を持たず、
設計入力へ確定した後に既存ゲートで判定する。SDK workflow toolはLLM subagent用で
shell・file操作を禁止するため、決定論的探索には使わない。

## SDK Conversation session境界

`acd.openhands.session.bootstrap`は`LocalConversation`へACD plugin、hooks、workspace、
`persistence_dir`、`AcdGateCritic`、`LLMSummarizingCondenser`を宣言的に接続する。
loop、history、state/event persistence、metricsはSDKへ委譲する。EventLog、
conversation state、metrics、condenser outputは経過でありpass evidenceではない。
fork/resume後も決定論的ゲートを再実行して合否を決める。SDK gitは設計入力のstale判定
への入力に限り、Evidenceの正は`Evidence.supports_pass(graph.revision)`である。

## agent-server運用境界

OpenHands SDK v1.42.1のagent-serverはACDの対象外である。serverの採用を検討する場合は、
認証、権限、Evidence境界、起動・保存・resume/forkの受入条件を定義する新規ADRを先に
起票する。現行の合否はCIまたは`run_in_workspace`の決定論的pipelineとgateが決める。

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
`required_evidence_ids`の各IDについて現revisionに一致する
`supports_authoritative_pass()`が必要である。
GD1基板pipelineは`build_electrical_evidence()`で電気Evidenceを生成し、
`out/gd1/evidence-electrical.json`へ書き出す。基板fabrication成果物の送信が
fail-closedになるのは、order policyの`required_evidence_ids`に含まれる両laneの
Evidenceについて、現revision一致かつauthoritative passを確認できない場合である。
現行policyは`evidence.gd1.electrical`と`evidence.gd1.mechanical`の両方を要求する。

Stopガードはorderガードより弱く、order policyのEvidence globで解決したファイルのうち、
dirtyな設計入力より新しいmtimeのvalidかつunknownなしEvidenceが存在する場合に限り
終了を許可する。mtimeの新しさはpass Evidenceではなく、`--valid-only`はStopガード専用
の新しさ確認である。`supports_pass()`は引き続きcommit済みrevision一致を要求し、
orderの合格側Evidenceは`supports_authoritative_pass()`を要求する。
該当しない場合は原因となった設計入力パスをreasonに列挙する。

## 実装していない境界

SDK機能の採否は[`openhands-sdk-capabilities.json`](openhands-sdk-capabilities.json)に整理し、
Markdown表は`scripts/verify_sdk_capabilities.py`から生成し、CIでdriftを検査する。
ACD機能としては、FW書き込み・機能測定、価格・在庫取得、
自働発注が未実装であり、将来構想である。実機Evidenceのschema契約と分類だけは
マイルストーン5.1、製造・組立受領の取り込みはマイルストーン5.2で実装済みである。
受領取り込みは`execution_context="host"`の`PhysicalEvidence`を入力更新の根拠として
生成するが、`supports_authoritative_pass()`は常に`False`であり、決定論的ゲートの
合格側へ昇格しない。
測定結果の入力反映は5.4のproposal生成と適用後validatorに限定し、反映policyに
明示された候補だけを提示する。proposalや実機Evidenceがgraph、rationale、policyへ
自動逆流する経路は持たず、入力更新は人または別の明示的工程が行った後に既存の
決定論的ゲートを再実行する。`rationale_required`が残る候補は適用可と扱わない。

## 工程境界

工程はS1（要件対話）、E1（部品選定と回路設計）、E2（アートワーク）、M1（筐体
コンセプト）、M2（筐体詳細）、S2（製造出力）、S3（製造・加工フィードバック）、
S4（試作立ち上げ）で構成する。各工程は入力ファイルを更新し、投影、独立再読込、
決定論的ゲートを実行する。工程の詳細な希望的仕様は保持せず、実装済みの境界だけを
本書の正とする。

## OpenHands実行境界

SDKが実行・対話・配布・観測を担い、ACDが契約・投影・合否を担う。エージェント入口は
SDK `ToolDefinition`に一本化し、`scripts/*` CLIは人間とCIの入口に限定する。実行形は
`LocalConversation`とworkspace APIを基点とし、runnerは事前build済みdigest固定server imageを
`DockerWorkspace`で使う。host経路はprovisional専用であり、経路unknownはfail-closedとする。
agent-server経路は対象外であり、採用時は新規ADRを起票する。
