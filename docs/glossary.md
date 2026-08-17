# 用語集

> ステータス: Draft

本書は、ACD文書で使う用語と工程IDの定義を正とする。各仕様書は定義を重複管理せず、
必要に応じて本書を参照する。

## 用語

| 用語 | 定義 |
|---|---|
| 探索仕様 | 配置・回転・配線の探索空間と評価方針をLLMが機械可読に宣言する契約。モジュール分解、相対配置制約、優先度、回転刻み方針、探索戦略、評価方針、緩和提案と設計根拠を持つ。座標・回転角の値そのものは含まない |
| 代理指標 | HPWL、混雑度、余裕などの安価に計算できる評価量。候補の順位付けに使い、合否根拠にしない |
| 整合化（legalization） | 生成した配置候補から、courtyard重なり、keepout侵入、外形逸脱、回転刻み違反などを幾何計算で除去または棄却する処理 |
| 回転刻み方針 | 部品カテゴリごとに許容する回転角の候補集合と根拠。`profiles/`配下の宣言を正とし、90度刻み以外はprofile許可とEvidenceを要する |
| 探索予算 | 反復回数、wall-clock、候補数、token、moneyの上限。探索仕様で宣言し、実測をEvidenceへ記録する。超過はfail-closedとする |
| fab profile | 製造者の能力下限・上限、推奨値、コスト・納期・品質への影響を、出所と確認日時付きで版管理する宣言データ |
| process allowance | 追加費用、納期増、または品質リスクを伴う工法を、要件nodeへの根拠参照付きで設計側が許容する宣言 |
| DFM finding分類 | `capability_violation`、`cost_or_lead_time_adder`、`quality_risk`、`unused_allowance`の分類 |
| `fab.order_intent` | 対象fab、基板条件、数量、実装面、色、表面処理、PCB／PCBA class targetなど、製造投影の要求を表す設計グラフnode |
| `fab.process_allowance` | 追加工程やコスト・納期・品質影響を、対象ruleと要件根拠付きで明示する設計グラフnode。capability violationには適用できない |
| DFM report | 独立測定した製造性判定、findings、未実装検査、測定値をgit commitとfab profileへ結び付けた投影 |
| fab package | Gerber/drill zip、JLCPCB形式BOM/CPL、DFM report、profile・overlay provenance、member content hashをまとめた製造投影 |
| デカップリング配置段 | 配置アルゴリズム第3段。設計グラフの`decoupling_target`から対象ICを決め、電源pinまでの距離を目的にコンデンサを配置する段 |
| export format | fab profileが宣言する製造出力の形式契約。BOM/CPLの列名・列順、単位、原点、座標系、面、回転基準、命名を含む |
| assembly class | fab profileが定義するPCBA工程区分。class ID、板条件、数量、色、表面処理、実装面、組立条件の組み合わせを表す |
| 自働 | 人間が異常を検知して止めるのではなく、異常を検知して自ら止まるToyota由来の自働化を指す。ACDでは安全境界、ゲート、fail-closedに適用する |
| 自動 | 人間の操作を介さず処理を実行する一般的なautomationを指す。自動検証は、判定結果が不合格またはunknownなら停止する自働の性質を必ず併記する |
| 投影 | 入力ファイルから再生成される派生成果物であり、入力ファイルを置き換えない |
| レビュー投影 | 入力ファイルから再生成し、別コンテキストのAIが観察するための投影。正ではなく、git commit・hash・版を保持する |
| 投影レビューPDCA | 入力ファイルの変更と対象工程を選ぶPlan、投影を生成するDo、AIが所見を作るCheck、決定論的ゲートで確認するActのループ |
| Evidence | ツール版、入力・出力hash、条件、結果、git commitを含む検証の根拠 |
| Rationale | 設計判断の採用理由、代替案、要求、provenanceを型付きrecordで保持する説明。合否権限は持たない |
| rationale coverage | graphの必須`(node, attr)`が有効なrationale recordで一意に覆われていることの決定論的検査 |
| Skill | SDKが提供するfrontmatter付きMarkdownの作業資材。工程手順や観点を配布するが、ACDの正や合否根拠ではない |
| plugin | SDKが提供するskills、hooks、MCP設定、agent定義、commandをまとめた配布単位。ACDの契約正ではない |
| AgentDefinition | SDKが提供するサブエージェントの役割定義。model、tools、skills、権限等を指定するが、ACDの判定正ではない |
| hook | SDKが提供するtool・prompt・session境界のイベント処理。防護や記録に使うが、ACDの合否根拠ではない |
| HookConfig | SDK pluginがhooks.jsonから読み込むhookイベント設定 |
| HookMatcher | SDK hookをtool名等へ適用する完全一致・ワイルドカード・正規表現の指定 |
| PreToolUse | tool実行前に呼ばれるSDK hookイベント。exit code 2で拒否する |
| Stop | agent終了前に呼ばれるSDK hookイベント。exit code 2で拒否する |
| exit code 2契約 | SDK command hookで2だけがブロックを表し、他の非0はログのみとなる契約 |
| AgentProfile | SDKが提供するmodel、LLM設定、MCP参照等のprofile。秘密情報を含まない参照で管理するが、ACDの正ではない |
| condenser | SDKが提供する会話contextの圧縮機構。Evidenceやゲート結果を置き換えず、ACDの判定正ではない |
| critic | SDKが提供する反復改善用の評価機構。ACDゲート結果を伝達できるが、scoreも合否の正ではない |
| ImageContent | SDKが画像URLをLLM入力へ渡す型。ACDでは視覚投影のレビュー入力に使うが、合否の正ではない |
| inspect_image_with_vision | SDK builtinの画像レビューtool。vision profileへ画像と質問を渡すが、応答はAIレビューであり合否権限を持たない |
| vision profile | 視覚入力を扱う別LLM profile。model、画像hash、renderer、解像度とともにEvidenceへ記録する |
| renderer | 視覚投影を生成した描画器の種別。描画結果のメタデータであり、決定論的ゲートの判定器ではない |
| EventLog | SDKが提供する型付き追記イベントの保存・分岐・復元機構。ACDはdomain payloadと合否の正を所有する |
| MCP server | 外部ツールadapterをプロセス・ライセンス境界の外側で提供する接続先。SDKは接続機構を提供するが、ACDが意味検証とEvidenceを所有する |
| DeclaredResources | SDK toolが並行実行時の共有resource keyを宣言する機構。ACDが必要なtoolを包んで排他キーを定義し、合否の正にはしない |
| WebhookSpec | agent-serverがイベントをbufferして外部URLへPOSTする仕様。配信保証は未確認のため、ACDはSDKの`EventLog`とcommitした入力ファイルを正とする |
| SecretSource | SDKがsecretを解決・注入する参照元。ACDはfab API等のsecret本体ではなく参照名だけを保持する |
| SessionStart | SDKのセッション開始hook。ACDでは独自の起動契約を追加せず、必要に応じて補助的に利用する |
| browser_use | SDKが提供するbrowser操作toolset。Phase 9の二次sourcingに使うが、Phase 11の発注経路には使わない |
| workspace | SDKが提供するagentの実行環境。ファイルや外部ツールを置けるが、ACDの設計グラフや合否の正ではない |
| DockerWorkspace／RemoteWorkspace | SDKが提供する隔離実行環境。ACDはLocalWorkspaceを採用せず、image digestまたはagent-server側の実行条件を固定する |
| noVNC desktop／VS Code経路 | agent-serverが同一workspaceを人間の観察・手修正へ公開する経路。GUI操作や画面表示はEvidence・合否の正ではない |
| Canvas extension | agent-serverの認証境界内へUIを配布するSDK拡張。ACDの承認・レビューUIに使えるが、Canvas frontend本体の可用性は未確認である |
| TestLLM | SDKが応答・例外を固定するテスト用LLM。決定論的回帰に使うが、実LLMの適格性やACDの合否を直接表さない |
| run_goal／GoalController | SDKがLLM judgeで停止条件を制御する機構。`GoalVerdict`は停止補助であり、Evidence・合否の正ではない |
| WorkflowTool | SDKがmap/reduceによる観点別agent分業を実行するtool。自然文の所見を束ねられるが、投影の意味的mergeや合否を行わない |
| switch_llm | SDKの会話中LLM切替tool。ACDは工程境界で明示的に使い、切替後のmodel／profile版をEvidenceへ記録する |
| LLMRegistry | SDKがusage ID別にLLMインスタンスと独立metricsを管理する機構。profile分離とコスト分解に使うが、合否の正ではない |
| FallbackStrategy | SDKがtransient error時に代替LLM profileを順に試すper-call fallback機構。fallback発生時は実体modelを記録し、レビュー中の版不定は`unknown`とする |
| RouterLLM | SDKが複数LLMを暗黙に選択するLLM。model版固定と両立しないためACDでは採用しない |
| persistent memory（MEMORY.md） | SDKがuser／project tierの`MEMORY.md`をプロンプトへ読み込む作業メモリ。プロンプト資材であり、契約の正や合否根拠ではない |
| preset／builtinサブエージェント | SDKが提供するtool束・agent構成と汎用サブエージェント（code-explorer等）。汎用作業へ再利用し、ACD工程agentは別途project levelで定義する |
| InstallationInfo／resolved_ref | SDKの`.installed.json`に保存される資材の解決済みcommit SHA情報。`requested_ref`だけの資材はACDではfail-closedとする |
| ConversationStats | SDKのusage単位metrics取得機構。`get_metrics_for_usage(usage_id)`でagent／profile別へ分解できるが、合否の正ではない |
| FileStore | SDKの保存抽象。`LocalFileStore`／`InMemoryFileStore`に合わせるが、SDKにremote実装はなくACD独自I/Fを増やさない |
| ACPAgent | ACP側がLLM・tool・実行を持つSDK agent。Evidence契約に必要なprompt・model・tool schema・logを確実に束ねられないためACDでは採用しない |
| OpenAI互換gateway | agent-serverのOpenAI chat completion形状の連携入口。照会・起票・状態取得に限定し、合否・承認・不可逆操作は駆動しない |
| StuckDetector | SDKの反復、error連続、monologue、交互パターン等の停滞検出機構。差し戻しを起動できるが、合否の正ではない |
| ゲート | 候補や成果物を次の工程へ進めるかを決定論的に判定する境界 |
| Assumption | 未確定の前提。確度、確定予定アクション、覆った場合の影響先を持つ |
| LibraryOverlay | 公式ライブラリを改変せず、プロジェクトローカルにfootprint等の差分を保持する仕組み |
| 対象範囲 | 趣味・研究・小規模試作の単一構成。1〜4層基板と3Dプリント・卓上切削の筐体を対象とする |
| 安全境界 | 禁止、承認必須、許可の三階層で設計対象を制限する規則 |
| fail-closed | 判定不能、unknown、版不明などを許可側へ倒さず停止する性質 |
| 設計入力 | Pydanticモデルで検証する入力ファイル。gitで変更履歴を管理する |
| fixture | 再現可能な入力、環境、期待結果、negative test条件を固定した検証用の最小データセット |
| golden task（ゴールデンタスク） | 代表的なfixtureを実行し、成果物、ゲート結果、Evidence、予算を継続的に回帰検証する基準作業 |
| negative test | 禁止、矛盾、失敗、unknownなどを意図的に入力し、処理が合格へ進まず停止することを確認する試験 |
| VibeBB | Vibe BreadBoardingの略称。重い検証を人間に見せず、対話から実機まで進めるACDの体験価値 |
| Q7/N7 | 将来の高信頼化調査で扱う品質分析手法。現在の合否機構ではない |
| SafetyBoundaryResult | `SB1`または`SB2`の判定について、危険区分、状態、根拠、git commitを記録する結果 |
| SB1 | 安全境界の予備判定段階。工程IDではなく判定段階のIDであり、工程`S1`で自然言語から実行する |
| SB2 | 安全境界の確定判定段階。工程IDではなく判定段階のIDであり、工程`E1`で設計グラフの述語から実行する。ゲートの正であり、`unknown`はfail-closedで停止する |
| RV1 | 旧文書で使われた工程内レビュー段階ID。現在の合否機構では使用しない |
| RV2 | 旧文書で使われた工程出口レビュー段階ID。現在の合否機構では使用しない |
| 工程ID | 設計フローの工程を共通（`S`）、電気（`E`）、機械（`M`）と番号で識別するID |
| tailoring（テーラリング） | 設計プロファイルに応じて検証項目、要求、Evidenceの重さを調整すること。ただし安全境界の最低条件は緩めない |
| netclass／ルールエリア | ネットへ共有制約を割り当てる定義と、領域へ局所制約を適用する設計グラフ属性 |
| カスタムルール | 表形式のクラス定義で表せない条件を、条件式・重大度・対象範囲付きで表すルール |
| courtyard | 部品の占有・干渉検査に使うfootprint側の領域情報。未定義時は検査能力をunknownとする |
| アニュラリング | 穴の周囲に残るランド幅。fab profileの最小値と突き合わせる製造属性 |
| テンティング | ビア等の開口をマスクで覆うか露出させる方針。既定値に依存せずグラフで固定する |
| stackup | 層構成、基板厚、誘電体、銅厚、マスク等の電気・機械共通の基板属性 |
| 派生状態 | ゾーン塗りつぶし等、正規設計グラフから再計算される検証対象の状態 |
| 面付け | 単体基板から製造用の別投影を生成する工程。行列、タブ、切り分け等を構造化する |
| variant／DNP | 実装可否・部品情報・出力対象を切り替える設計条件。外形・配置・配線は共通とする |
| 内部接続ピン | 部品内部で電気的に接続されたピンを表すライブラリ属性 |
| バックアノテーション | 投影側の変更を上流へ戻す同期処理。ACDでは投影を正へ逆流させない |
| refdes／安定identifier | 生成表示用の参照記号と、変更に対して安定した内部識別子の組 |
| 面付け投影 | 面付けパラメータから生成する、単体基板とは別の製造用投影 |
| 形式版 | ECADファイルの保存・解釈契約を識別する版。ツール版と併せてEvidenceへ記録する |

## 工程ID体系

工程IDは、共通を`S`、電気を`E`、機械を`M`で表す。

| 新ID | 工程 |
|---|---|
| `S1` | 要件対話 |
| `E1` | 部品選定と回路設計 |
| `E2` | アートワーク |
| `M1` | 筐体コンセプト |
| `M2` | 筐体詳細 |
| `S2` | 製造出力 |
| `S3` | 製造・加工フィードバック |
| `S4` | 試作立ち上げ |

旧文書との対応は次のとおりである。

| 旧ID | 新ID |
|---|---|
| `S1` | `S1` |
| `S2` / `E2` | `E1` |
| `S3` / `E3` | `E2` |
| `M2` | `M1` |
| `M3` | `M2` |
| `S4` | `S2` |
| `S5` | `S3` |
| `S6` | `S4` |
