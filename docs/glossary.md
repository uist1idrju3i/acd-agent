# 用語集

> ACD文書で使う用語の定義を示す。

| 用語 | 定義 |
|---|---|
| 設計入力 | Pydanticモデルで検証し、gitで履歴管理する入力ファイル。 |
| Design Graph | 電気・機械・製造意図を表すACDの正規設計モデル。 |
| 投影 | 入力から再生成され、入力を置き換えない派生成果物。 |
| レビュー投影 | AIが観察するための機械可読または視覚的な投影。 |
| 視覚投影provenance | 視覚投影の入力revision・入力hash、renderer種別・版、正規化後画像hash、測定解像度、生成時刻、再生成検査を記録する情報。 |
| SVG正規化規則 | KiCad SVGの非決定な`<title>`要素だけを固定文字列へ置換して比較可能にする規則。 |
| Evidence | ツール版、入力・出力hash、条件、結果、commitを含む検証根拠。 |
| 実機Evidence | 実機または仮想実機から取得した測定機器、条件、時刻、対象revision、測定量を含む入力更新用のEvidence。決定論的ゲートのauthoritative合格には使わない。 |
| measured/virtual分類 | `measured`は実機で取得した測定、`virtual`はRenode等の仮想実機ログを表す分類。`virtual`は実測の代替にならない。 |
| 測定量 | 名前、単位、値、期待範囲、許容差を持つ実機Evidenceの数値記録。 |
| 期待範囲 | 測定量が満たすべき下限・上限と許容差による決定論的な値域。 |
| 受領record | fabまたは実装業者から受領した成果物、検査レポート、送付manifest、出所、時刻を記録する契約。 |
| 見積record | fabまたはdistributorの価格・在庫・納期・実装可否を、出所URL、取得時点、有効期限、対象revisionとともに記録するfixture入力契約。発注許可は持たない。 |
| 一次確認区分 | 見積費目の金額が出所で直接確認された`primary`か、推定・派生の`inference`かを示す区分。確定値の読み出しは`primary`に限定する。 |
| OrderScope | 発注対象のrevision、fab profile、相手方、供給者、費目、送料・税、機械部品、通貨を明示する合算入力契約。発注許可は持たない。 |
| 区分別小計 | 見積record群の費目をcategoryごとに合算した、総額の再現可能な内訳。 |
| 内訳hash | 区分別小計、総額、各見積canonical hash、対象revisionを正規化して得る合算結果のhash。 |
| OrderPolicy | 発注hookの既存条件、設計graphパス、両lane Evidence ID、発注総額上限を厳格に宣言する契約。 |
| 発注前最終ゲートrecord | 現行revision、7.2総額、上限額、Evidence hash、policy hash、判定時刻を集約した非Evidence record。新しいpass authorityや発注権限は持たない。 |
| order_total_limit | `OrderPolicy`に宣言する、最小通貨単位の整数・通貨・最小単位桁数による発注総額上限。 |
| side-effect journal | 7.3の許可recordを参照する不可逆操作の事前予定と事後結果を、entry hash連鎖付きJSON Linesへ追記する記録。Evidence、合否権限、発注許可ではない。 |
| journal entry hash | side-effect journal entry本体をcanonical JSON化したhash。entry自身の内容を検証し、直前entry hashと連鎖する。 |
| execution mode | journal entryに記録する`dry_run`または`real`。pre/postで一致させ、dry-run組は実発注完了とみなさない。 |
| order execution dry-run | 7.3許可と7.4 journalを前提に、secret値や外部送信を伴わず、決定論的な送信payloadとreceiptを記録する実行。 |
| real-order disabled boundary | 実providerへの送信を未有効化として明示的に拒否する7.5の停止境界。 |
| 送付manifest | 製造・組立へ送付した成果物の相対path、content hash、対象revisionを記録するmanifest。 |
| 突合（reconciliation） | 送付manifestと受領recordの成果物一覧、hash、対象revisionを決定論的に比較する処理。 |
| 検査レポート参照 | 受領recordから検査レポートの識別子、出所URI、発行時刻、content hashをたどる参照。 |
| 機能測定run record | FWの版、成果物、生ログ、測定機器、期待条件、対象revision、時刻を1回の実行単位として宣言する契約。 |
| LED capture | LEDの`timestamp_s,level`時系列を保存した生ログ。周期、周波数、duty比の独立測定へ使う。 |
| 書き込み検証 | `esptool.py`相当のflash logで、対象chip、app imageの`app_flash_offset`・サイズ、書き込み行と`Hash of data verified.`行の件数、`Hard resetting`完了を照合する処理。 |
| シリアル温湿度ログ | `I (12345) gd1: temp=25.31C rh=48.20%`形式の生ログ。tagに一致するセンサ行だけを厳格parseし、温度、湿度、値域、周期を独立parserで測定する。 |
| 反映policy | 実機Evidenceのmeasurement nameを、対象graphのnode／属性、反映種別、許容差、decision kindへ明示的に対応付ける宣言。推測による対応付けは行わない。 |
| proposal document | 実機Evidenceに基づく設計入力属性の変更候補、根拠Evidence、rationale要否、入力・出力hashを保持する派生文書。入力graphへ自動適用しない。 |
| stale Evidence | 対象graphのrevisionと一致せず、現行設計入力の根拠に使えないEvidence。 |
| 適用後validator | 人または別工程が更新したgraphについて、proposalに宣言された属性だけが提案値へ変わったことを検査する決定論的検証。 |
| execution context | `container`、`host`、`unknown`で表すToolEnvelopeの型付き実行場所。 |
| authoritative Evidence | revision一致、既知provenance、digest固定containerを満たし、合格側へ使えるEvidence。 |
| provisional Evidence | `supports_pass()`は満たすがdigest固定container要件を満たさず、参考に限るEvidence。 |
| Rationale | 採用理由、代替案、要求、出所を保持する型付き設計根拠。 |
| rationale coverage | 必須属性が有効なrationale recordで覆われている状態。 |
| ゲート | 成果物を次工程へ進めるか決定する境界。 |
| fail-closed | unknown、未実行、版不明を許可側へ倒さず停止する性質。 |
| ToolEnvelope | ACD toolの入力、出力、provenance、エラーを包む契約。 |
| ToolDefinition | SDKへACDの決定論的入口を登録する定義。 |
| Skill | SDKが配布する工程手順や観点を記述した作業資材。 |
| plugin | Skill、hook、agent定義、commandをまとめる配布単位。 |
| AgentDefinition | agentの役割、model、tool、Skill、権限を定義する資材。 |
| role prompt manifest | role promptのrepo相対path、資材・本文hash、PromptSection名、cache tierを固定するmanifest。Evidenceではない。 |
| prompt section | OpenHands SDKの`PromptSection` protocolに適合するL2 role promptの構造。 |
| model routing policy | roleごとのmodel、SDK `usage_id`、profile識別子とcanonical hashを固定する宣言。秘密情報を持たず、Evidenceではない。 |
| judge model | goalの完了評定を補助するrole別model。決定論的gateの合否やEvidenceを決めない。 |
| observation store | L3観測を`FileStore`へ保存するACD側経路。Evidenceと設計入力は対象外で、`pass_evidence=false`を固定する。 |
| hook | toolやsession境界で防護・記録を行うイベント処理。 |
| critic | 反復改善を操舵する評価機構。合否権限は持たない。 |
| Conversation | SDKが管理する対話、履歴、状態、永続化の単位。 |
| GoalController | 目標達成の反復停止を補助するSDK機構。 |
| DockerWorkspace | digest固定server imageでゲートを実行するSDK workspace。authoritative Evidenceの唯一の実行経路。 |
| LocalConversation | 現行ACDが採用するローカルConversation経路。 |
| agent-server | SDKのREST/WebSocket等を提供する将来構想のserver経路。 |
| L1/L2/L3 | L1は判定、L2は操舵、L3は観測を表す責務層。 |
| 自働 | 異常を検知すると人の判断を待たず安全側へ停止する性質。 |
| 代理指標 | 候補順位付けに使う安価な評価量。合否根拠にはしない。 |
| fixture | 入力、環境、期待結果、negative条件を固定した検証データ。 |
| negative test | 禁止・矛盾・unknownが合格へ進まないことを確認する試験。 |
| golden task | 成果物、ゲート、Evidence、予算を回帰検証する代表作業。 |
| 工程ID | `S`、`E`、`M`と番号で表す設計工程の識別子。 |
| SafetyBoundaryResult | 安全境界判定の状態、根拠、commitを記録する結果。 |
| SB1/SB2 | 安全境界の予備判定／確定判定段階。 |
| fab profile | 製造能力、推奨値、出所、確認日時を版管理する宣言データ。 |
| DFM finding | 製造性に関する独立測定結果と分類。 |
| LibraryOverlay | 公式ライブラリを改変せず差分を保持する仕組み。 |
| Canvas | GUIベースのOpenHands拡張経路。ACDでは採用しない。 |
| VibeBB | Vibe BreadBoarding。対話から設計・検証へ進むACDの体験価値。 |
| 安全境界 | 禁止、承認必須、許可の三層で設計対象を制限する規則。 |
| 対象範囲 | 趣味・研究・小規模試作の単一構成。1〜4層基板と卓上加工筐体を対象とする。 |
| 探索仕様 | 配置・回転・配線の探索空間、制約、戦略、評価、緩和方針を宣言する契約。 |
| 探索予算 | 反復回数、wall-clock、候補数、token、money等の上限。超過はfail-closed。 |
| 整合化（legalization） | 配置候補から重なり、keepout侵入、外形逸脱等を幾何計算で除去する処理。 |
| 回転刻み方針 | 部品カテゴリごとの許容回転角集合と、そのprofile上の根拠。 |
| process allowance | 追加費用、納期、品質影響を伴う工法を設計側が許容する宣言。 |
| DFM finding分類 | `capability_violation`、`cost_or_lead_time_adder`、`quality_risk`、`unused_allowance`。 |
| `fab.order_intent` | 対象fab、基板条件、数量、実装面、色、表面処理等の製造要求node。 |
| `fab.process_allowance` | 対象ruleと要求根拠付きで追加工程・影響を表す設計node。 |
| DFM report | 独立測定した製造性判定、finding、未実装検査、測定値の投影。 |
| fab package | Gerber/drill、BOM/CPL、DFM report、profile provenanceをまとめた製造投影。 |
| export format | BOM/CPL列、単位、原点、座標系、面、回転、命名を含む出力形式契約。 |
| assembly class | 板条件、数量、色、表面処理、実装面、組立条件を組み合わせたPCBA区分。 |
| courtyard | footprintの占有・干渉検査領域。未定義時は検査能力をunknownとする。 |
| アニュラリング | 穴の周囲に残るランド幅。fab profileの最小値と照合する。 |
| テンティング | via等の開口を樹脂・ソルダーマスクで覆う製造処理。 |
| stackup | 基板層、誘電体、厚さ、銅厚等の積層定義。 |
| 面付け／面付け投影 | 複数基板を製造パネルへ配置する定義／その派生投影。 |
| variant/DNP | variantは構成差分、DNPはDo Not Populate指定。 |
| netclass／ルールエリア | ネット共有制約／局所領域制約の設計グラフ定義。 |
| カスタムルール | 条件式、重大度、対象範囲を持つ表形式外の制約。 |
| 内部接続ピン | 外部端子でなく部品・モジュール内部接続に使うpin。 |
| バックアノテーション | 実装・測定結果を設計入力へ反映する更新。根拠とrevisionを記録する。 |
| refdes／安定identifier | 部品参照名／再生成後も同一対象を追跡する識別子。 |
| 形式版 | ファイル形式・schemaの版。入力と出力の互換性確認に使う。 |
| 派生状態 | 入力から生成された成果物の状態。設計入力の正ではない。 |
| Assumption | 未確定の前提。確度、確定予定、影響先を記録する。 |
| LibraryOverlay | 公式ライブラリを改変せずプロジェクト固有差分を保持する仕組み。 |
| tailoring | profileに応じて検証項目やEvidenceの重さを調整すること。最低安全条件は緩めない。 |
| unclassified | 必須にも明示免除にも分類されない属性。coverageをfail-closedにする。 |
| Q7/N7 | 品質分析・計画の作業手法。合否機構ではない。 |
| InstallationInfo／resolved_ref | SDK資材の要求refと解決済みcommit SHAを表す情報。 |
| TestLLM | 応答・例外を固定するSDKテスト用LLM。実LLMや合否を直接表さない。 |
| 投影レビューPDCA | 入力と工程を選ぶPlan、投影生成Do、AI所見Check、ゲート確認Actのループ。 |
| 自動 | 人の操作なしに処理する性質。異常時に安全側へ止まる自働と区別する。 |
| デカップリング配置段 | `decoupling_target`から対象ICを決め、電源pinまでの距離を目的に配置する段。 |
| mechanical section view | ゲート通過後のauthoritative assembly STEPを宣言したXY平面とoffsetで切断し、XY平面へ移して生成する機械laneのL3 SVG観測。 |
| mechanical interference view | authoritative enclosure STEPとMechanicalLaneのcomponent bodyの交差領域を、存在時は別layerで描き、ゲート実測最大干渉体積と突合するL3 SVG観測。交差なしはprojection recordの体積0・領域なしで表す。 |
| mechanical visual renderer provenance | build123d/OCP版、STEP入力hash、revision、正規化規則、出力hash、再生成結果を保持する機械視覚投影の出所情報。 |
