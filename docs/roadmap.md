# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

本書は現在地、現行実装計画、未了・計画中マイルストーンの完了条件、契約・ADR・plugin資材との
対応、横断的な検証要件を扱う。達成済みフェーズの完了条件と実装記録は
[`roadmap-completed.md`](roadmap-completed.md)、マイルストーン化していない将来構想は
[`roadmap-future.md`](roadmap-future.md)へ分離している。

## 現在地

OpenHands plugin、11 Skill、5 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
GD1基板・筐体・FW pipeline、SDK hooksによるfail-closed境界を提供する。マイルストーン1〜8、
9.1〜9.2、11.5、12、14.1〜14.15、14.19、15.1〜15.13は達成済みであり、完了条件と実装記録は
[`roadmap-completed.md`](roadmap-completed.md)を正とする。

決定論的ゲートのauthoritative Evidenceはdigest固定container実行だけが生成する。
runnerとCIは事前build済みdigest固定server imageによる`DockerWorkspace`経路へ移行済みで、
hostはSDK `LocalWorkspace`によるprovisional実行に限定し、経路unknownはfail-closedとする。
lock済みdigestのpullは`scripts/pull_locked_image.py`が正であり、docker CLIへはACD側から
明示timeoutとmemory上限を与える。agent-server package、REST/WebSocket API、
server側のresume/forkは[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)により
対象外であり、[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)はSupersededである。
採用する場合は認証・権限・Evidence境界の受入条件を定義した新規ADRを起票する。
SDK workflowは採用しない。

scope（2026-08-31）として、自動発注と実機測定は将来機能・非対象とし、既存コード
（7.5のdry-run、5.1〜5.4の実機Evidence取り込み）は残置するが決定論的loopの必須段には
含めない。供給者からの価格・在庫・納期・実装可否の自動取得、実providerへの送信と
実発注完了、量産対応も将来範囲である。現行必須scopeは製造提出データ（Gerber一式・drill・
gbrjob・gerbers.zip・BOM・CPL・fab-package manifest・筐体STEP／3MF／STL）の生成と
独立reload・hash・DFM・幾何検査、およびその単一L1判定（14.19のU-5）である。
GD1実機の`measured` Evidenceは未取得で、検証はfixtureベースである。

第6回実機実測（2026-08-31、新規VPS・新規OpenHands workspace、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 13節、
[`examples/golden-design-1-vps-20260901/`](../examples/golden-design-1-vps-20260901/)）では、
GD1に限れば要件検証から製造提出判定・authoritative Evidence検証まで決定論的経路が
端から端まで通過した。一方、新規specは`silkscreen`宣言の不足でfail-closedし、GUI会話は
`acd_*` tool未登録のまま決定論的CLIへ倒れ、会話の最終報告がL3記録だけで合格を述べた。
これらはV-1〜V-10として14.20・14.21・15.17〜15.19で扱う。実測で全laneを通過した設計は
GD1と`fixtures/mini-blink-dongle/`の2件であり、GD1非依存の達成判定はW-1〜W-4（14.21）で行う。

残る未了は、14.16（FW lane専用の候補生成と配置テストの環境非依存化）、14.17のS-3
（ambient install経路の配布形態）と復帰成立実行の実測記録、14.18の復帰成立runの
wall-clock記録、14.20、14.21、15.14〜15.19、および計画段階のマイルストーン9.3〜9.5、
10、11.1〜11.4、13、16〜21である。KiCad由来SVGのfit-to-board化（用紙余白の除去）は
未実装であり、8.5の電気視覚照合が図枠のtitle blockを読むため現行exportを維持し、
極小表示の所見は20.4の可読性検査で扱う。

## 現行実装計画

| 順 | マイルストーン | 達成条件 | 現状 |
|---|---|---|---|
| 1 | 契約と再現可能な投影 | graphをPydanticで検証し、同一入力から投影・provenance・hashを再生成できる | 達成 |
| 2 | 電気レーンの独立検証 | ERC、routing収束、SES import、DRC、Gerber/drill生成、独立再読込、silkscreenゲートを通す | 達成 |
| 2.1 | 設計述語ゲートと負例 | USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界（`SafetyBoundaryResult`）、ピン・FW整合の6ゲートを実装し、GD1-NEG-001〜008とsilkscreen座標表のpinning testを整備する | 達成 |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成（3.1で実機組み付け発見の不具合を修正） |
| 4 | plugin委譲とSDK tool境界 | Skill/agent/command/toolをSDKでloadし、既存gateをfail-closedで公開する | 達成 |
| 4.1 | SDK hooks境界 | 投影保護、Evidence発注ガード、Stop、probe、文書検証を既存判定の呼出しとして実装する | 達成 |
| 4.2 | 決定論的gate critic | Design Graph revision、Evidence、製造manifestだけで二値criticを評価し、SDK反復を操舵する | 達成 |
| 4.3 | 決定論的探索lane | 独立width armを固定順で並列集約し、探索AgentDefinitionは候補とprovenanceだけを返す | 達成 |
| 4.4 | SDK機能移譲 | SDKのcontext、routing、保存、観測、設定、credential、profile、workspaceへ責務を段階移譲する | 達成（hostは`LocalWorkspace`によるprovisional専用、authoritative経路はdigest固定`DockerWorkspace`） |
| 4.5 | 能力カタログ検査の強化 | 採用行の代表APIまたはドメインがACDコード・plugin資材・テストのどこで使われているかを参照検査し、間接利用とテスト利用の参照先を種別付きで宣言してdriftをfail-closedで検出する | 達成 |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 5.1〜5.4実装（GD1実機measured Evidence未取得） |
| 6 | 実行基盤のDockerWorkspace一本化 | 事前build済みdigest固定server imageでゲートを実行し、authoritative Evidence経路を単一化する | 6.1〜6.6完了（tools／server digest記録済み、runnerとCIは`DockerWorkspace`経路へ移行済み、pull入口とtimeout境界を実装） |
| 7 | 発注前最終ゲートと自働発注 | 期限付き見積入力と全ゲート再実行を条件に、side-effect journalへ記録した発注だけを許可する | 7.5 dry-run・拒否境界まで達成（実発注は本範囲外） |
| 8 | 視覚投影レビュー基盤 | 画像生成、画像hash・renderer種別・解像度の記録、機械可読投影との決定論的照合、レビュー観点の記録、`ImageContent`／`inspect_image_with_vision`経路、SSRF境界を実装する | 8.1〜8.6実装済み、8.5はFW lane照合まで実装済み |
| 9 | 生成文書lane | 設計入力、投影、ゲート結果、Evidenceから再現可能な製品・品質・レビュー文書を生成する | 9.1〜9.2実装済み（9.3〜9.5は計画） |
| 10 | シミュレーション解析lane | 電気・機械・FWのprovisional解析を追加し、決定論的ゲートを置き換えずに結果を文書へ統合する | 計画 |
| 11 | 機構設計拡張 | 可動機構、干渉、機構向けDFM、部品込み3D統合を機械laneへ追加する | 計画 |
| 12 | 設計ナレッジQA | 設計知識源への出所引用付きQAと公開用FAQ生成を、unknown停止と会話ログ公開除外の規則付きで提供する | 12.1〜12.5達成 |
| 13 | 既存製造品の救済（ワークアラウンドlane） | 既存製造品に対する追加工・FW修正の救済差分を記録し、派生graphへ既存ゲートと実施可能性を再適用する | 計画 |
| 14 | VibeBB単体成立（会話駆動の設計反復） | 汎用エージェントの代行なしで会話から設計反復を回し、候補生成・検証・失敗回復を行う | 進行中（14.1〜14.15・14.19は達成。14.16、14.17のS-3、14.18の実測記録は未了で、GD1以外の設計によるend-to-endの成立は未実証。残関門は14.20・14.21） |
| 15 | 運用と文書の整備 | 運用・文書側の改善を整備し、ツール意味論、発注判定、取得・リリース手順、ログ要約を記録する | 15.1〜15.13達成（15.14〜15.19は計画） |
| 16 | 設計能力の拡張 | 多層基板、階層graph、バッテリ、EMC/ESD、DFT、構造安全性の設計契約とゲートを拡張する | 計画 |
| 17 | 部品・サプライチェーン統治 | 部品ライブラリ、ライフサイクル、代替、BOMコンプライアンスとコスト検討を統治する | 計画 |
| 18 | 量産・出荷準備lane | ブリングアップ、panelization、DFA、出荷検査文書と検査FWを整備する | 計画 |
| 19 | FWセキュリティと検証拡張 | secure boot、暗号化、OTA、QEMUカバレッジと実機HILを拡張する | 計画 |
| 20 | 改訂管理とレビュー運用 | ECO、graph差分、PR提示、視覚品質、トークン・コスト予算を運用する | 計画 |
| 21 | 構想ブラッシュアップと分野横断の責務割当 | ものづくりアイデアを宣言contractとして受け取り、利用者との対話で洗練して要件へ確定し、機能の配置先を宣言と決定論的検査で割り当てる | 計画 |
| — | agent-server採用判断 | 対象外を維持し、採用する場合だけ新規ADRで認証・権限・Evidence境界を定義する | 対象外 |

各マイルストーンとフェーズの完了条件は、(1)入力と出所、(2)実装、(3)正常系、
(4)negative/fail-closed、(5)再現性の5要素で確認する。SkillやAIの所見だけでは完了としない。
以降のフェーズ表は各要素の確認内容を定義する。
達成済みフェーズの表は[`roadmap-completed.md`](roadmap-completed.md)へ移した。

## マイルストーン9: 生成文書lane（SKILL拡張）

成果物公開・品質保証・レビューに使う文書を、設計入力・投影・ゲート結果・Evidenceから
決定論的に生成する。生成文書はL3観測（提示物）であり、合否権限を持たず、
投影を設計入力へ逆流させない不変条件を維持する。文書はworkspaceの`out/docs/`へ格納し、
入力hash・生成ツール版・テンプレートhashをprovenanceとして記録する。
必要な入力（ゲート結果、Evidence、視覚投影）が欠落する場合は生成をfail-closedで停止し、
「問題なし」とは解釈しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 9.1 | 製品説明README生成SKILL | 図解入りの製品説明`README.md`を生成する。Design Graphの仕様（MCU、電源、センサ、I/F）、BOMサマリ、視覚投影（回路図・配置・電源ツリー・筐体断面）を埋め込み、公開用にライセンス・帰属注記を自動付与する |
| 9.2 | 取扱説明書生成SKILL | 機能説明・接続手順・LED表示の意味・書き込み手順・安全注意を、graphとFWピン投影（`acd_pins.h`相当）から生成する。値はすべて入力由来とし、推定値を書かない |
| 9.3 | 品質文書生成SKILL | ゲート結果（ERC/DRC/DFM/機械/FW）、rationale coverage、authoritative Evidence、既知の未実装チェック一覧から検査成績書・トレーサビリティレポートを生成する。Evidence欠落・revision不一致は生成失敗として停止する |
| 9.4 | レビュー資料生成SKILL | レビューチェックリスト、視覚投影一式、前revisionとのgraph差分、DRC/DFM所見の要約を1パッケージへまとめ、`acd-reviewer`agentの入力にする |
| 9.5 | 多言語出力 | 9.1〜9.4の文書を日本語・英語で再現可能に生成する（テンプレート分離、値の翻訳はしない） |
| 9.6 | テーマソング生成SKILL | LLM agentが製品専用ジングルを構造化JSONで提案し、Skillが契約検査してMIDIへ決定論的にレンダリングする。提案が無ければgraph由来の決定論composerへfallbackし、provenance付きで生成する（ADR-0048） |

9.1と9.2は`acd-product-docs` Skill、9.6は`acd-theme-song` Skillとして実装済みで、
9.3〜9.5は計画である。

## マイルストーン10: シミュレーション解析lane

電気・機械・FWの解析をprovisional検証として追加する。解析結果はL2操舵・L3観測であり、
決定論的ゲートの合否を置き換えない。閾値との比較をゲート化する場合は、
入力・ツール版・メッシュ／刻み幅を固定した再現可能な決定論的判定として個別に定義する。
GPLツール（ngspice、CalculiX等）はsubprocess実行に限定し、ACDへのimport結合をしない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 10.1 | 電気シミュレーション（SPICE） | 同梱済みngspiceで、graphから電源系ネットリスト（LDO・デカップリング・LED電流・I2Cプルアップ）を決定論的に抽出して過渡・動作点解析を実行し、値域チェックを行う |
| 10.2 | 電源系解析（PDN/IR drop） | ガーバ・銅箔形状から電源経路の断面積・電流密度・IR dropを推定し、閾値超過を停止側の所見として報告する |
| 10.3 | 機械解析（質量・熱・構造） | 質量特性・肉厚（実装済み）に加え、熱抵抗の簡易推定と、FEM（CalculiX等のCLI）による落下・応力・熱の解析経路を追加する |
| 10.4 | FW解析 | 静的解析（clang-tidy相当）、スタック使用量解析、QEMU上のペリフェラルスタブ（SHT40応答モデル等）による機能テストを追加し、仮想検証の範囲を広げる |
| 10.5 | 解析結果の文書統合 | 10.1〜10.4の結果を9.3品質文書・9.4レビュー資料へ取り込む |
| 10.6 | ワーストケース解析（WCA） | 10.1の公称値解析に加え、偏り成分（公差中心のずれ、温度・経時による系統的変化）は決定論的に累積し、独立なばらつき成分はRSSで合成する解析を追加する。使用した公差表・環境条件・変動源の分類と合成方法をEvidenceへ記録し、公差表または環境条件が宣言されていない場合はunknownとして停止側へ集約する。16.2の電力バジェットは平均ではなくピーク需要で評価する |

10.1〜10.6は計画である。

## マイルストーン11: 機構設計拡張

筐体（静的な箱）から機構（可動・組立）へ機械laneを拡張する。設計述語を追加する範囲は
マイルストーン14.2の契約registryを前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 11.1 | 機構要素ライブラリ | スナップフィット、ヒンジ、ボタン・ライトパイプ、ボス・リブをbuild123dのパラメトリック部品として追加し、寸法根拠をrationale必須にする |
| 11.2 | 可動干渉チェック | 可動範囲のスイープ干渉を決定論的ゲートとして追加する（開閉・押下ストローク） |
| 11.3 | 製造性チェック拡張 | 3Dプリント／射出成形向けのDFM（最小肉厚、抜き勾配、オーバーハング）を機械laneゲートへ追加する |
| 11.4 | 部品込み3D統合 | KiCad 3Dモデルの選択的同梱と連携し、基板＋部品＋筐体の統合干渉チェックと組立図投影を生成する。選択的同梱にはimageサイズ増加、publish時間の増加、digestの再lock、ADR-0028のprovenance更新が伴う |
| 11.5 | 筐体の干渉解決探索（C-1） | 達成。宣言された筐体寸法のbounded候補を決定論的に列挙し、候補ごとに筐体pipelineの機械gateを評価してL2 reportへ記録する。探索結果はgraphへ自動確定せず、L1 gateとEvidenceの権限を変更しない |

11.1〜11.4は計画であり、11.5は達成済みである。

## マイルストーン12: 設計ナレッジQA

完成した設計の知識源（design graph、rationale record、ゲート結果、Evidence、生成文書、
git履歴、revision差分、会話ログ）を照会可能なナレッジとしてまとめ、製品仕様、使い方、
トラブルシューティング、設計根拠、歴史的経緯の質問に出所の引用付きで答える。
対象ユーザは設計者・開発チームと、成果物を受け取る第三者（製品ユーザ・レビュア）の両方とする。
回答はL2操舵・L3観測であり、合否権限を持たない。回答は必ず出所（rationale ID、
Evidenceファイル、コミット、文書パス）を引用し、知識源から導出できない質問には
unknownと答え、推測で補完しない。会話ログは内部向けQAの知識源にのみ含め、
公開用FAQの知識源には含めない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 12.1 | ナレッジ索引契約 | graph・rationale・ゲート結果・Evidence・生成文書・git履歴・会話ログを、出所種別と参照パス付きで列挙する索引contractを定義する。欠落した知識源はunknownとして記録する |
| 12.2 | 対話QA SKILL | OpenHands会話内で製品仕様・使い方・トラブルシューティング・設計根拠・歴史的経緯の質問に、索引contractの範囲で出所引用付きの回答を返すSKILL（例: `/acd:ask`）を追加する |
| 12.3 | トラブルシューティング知識の構造化 | 症状→確認手順→期待値（LED表示、I2Cアドレス、期待シリアル出力等）をgraphとFW投影から機械可読に導出し、12.2と公開用FAQの共通知識源にする |
| 12.4 | 公開用FAQ生成 | 成果物と一緒に公開できるFAQ・ナレッジ文書を`out/docs/`へ生成する（マイルストーン9の文書laneと同じprovenance規則）。知識源から会話ログを除外し、除外した旨をprovenanceへ記録する |
| 12.5 | 歴史的経緯QA | git履歴・revision差分・会話ログ（内部のみ）・ECO記録から「いつ・なぜ変わったか」を出所引用付きで回答する経路を追加する |

12.1〜12.5は`acd-design-knowledge` Skillと`/acd:ask` commandとして実装済みである。
運用手順は[`operations.md`](operations.md)の設計知識laneを参照する。

## マイルストーン13: 既存製造品の救済（ワークアラウンドlane）

すでに製造・組立を終えた個体（在庫品・出荷済み品）に生じた不具合を、基板を作り直さずに
救済する経路を追加する。ここでいうワークアラウンドとは、新revisionの製造データを
発注し直す代わりに、**追加工**（ジャンパ線の追加、部品の後付け・除去・定数変更、
パターンカット、手はんだ、筐体の追加切削・穴あけ）と**FW修正**（ピン割当変更、
タイミング・閾値の変更、機能の縮退・無効化）だけで、対象個体を許容可能な動作へ
戻す暫定的な回復手段を指す。設計としての本修正ではなく、個体群に対する
意図的な逸脱の適用であり、[`design-requirement-variation.md`](design-requirement-variation.md)の
要件変更（新規設計・新revision）とは別の経路として扱う。

設計原則は次のとおりとし、既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩めない。

- ワークアラウンドは設計入力の正を書き換えない。graphへの本修正はECO（マイルストーン20.1）
  として別に起票し、ワークアラウンドrecordは適用対象個体に対する逸脱の記録に限る。
- 救済状態は`revision + workaround ID`で識別する（例: `rev1.0+WA-001`）。
  対象個体はロット・シリアル単位で明示し、未適用個体を適用済みと同一視しない。
- 救済可否はSKILLの所見ではなく決定論的ゲートが決める。追加工差分から派生graphを導出し、
  ERC、設計述語ゲート（USB CC、strapping pin、I2C pull-up、デカップリング、電源境界、
  ピン・FW整合）、DRCの影響範囲、機械干渉を再実行する。導出不能・ゲート未実行・unknownは
  「救済不可」として停止し、「問題なし」とは解釈しない。
- FW修正だけで救済する場合も、派生graphに対してピン・FW整合ゲートを再実行する。
- 電源経路、保護素子、安全境界に関わる追加工は承認必須とし、機能の縮退・無効化を伴う救済は
  「制約付き救済」として明記する。制約付き救済は合格を意味しない。
- 追加工の実施可能性（工具アクセス、部品の向き、手はんだ可否、筐体分解の可否）を
  DFA観点として判定に含め、物理的に不可能な追加工を候補にしない。
- 作業後の実測はマイルストーン5の実機Evidence契約に従う個体単位のrecordとし、
  L1のauthoritative合格へ昇格しない。
- 不具合recordのcloseは是正の実施だけで完了としない。同一原因が影響し得る箇所の水平展開の列挙と、再現条件でのゲート再実行または実測Evidenceによる有効性確認をclose条件とする。説明だけでcloseしない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 13.1 | 不具合record契約 | 症状、再現条件、発生率、影響機能、影響個体範囲（ロット・シリアル）、根本原因候補を宣言contractとして定義する。原因が導出できない場合はunknownとして記録し、救済候補の立案へ進めない。併せて水平展開の列挙（同一部品・同一トポロジ・同一ルール適用箇所・同一fixture・同一プロファイルをgraph上で機械的に検索した結果と、対象外にした箇所の理由）を必須項目とし、列挙結果が空の場合は「探索して該当なし」と「未探索」を区別して記録する。未探索はunknownとして停止側へ集約し、救済候補の立案へ進めない |
| 13.2 | 追加工差分contract | 追加工を`cut`（パターンカット）、`add`（部品・配線の追加）、`remove`（部品の除去）、`replace`（定数・型番の変更）、`mechanical`（筐体の追加加工）の型付き差分として宣言し、元graphへ適用した派生graphを決定論的に導出する。差分は投影として扱い、設計入力へ逆流させない |
| 13.3 | 救済可能性ゲート | 派生graphへ既存の電気・機械・FWゲートを再実行し、追加工の実施可能性（DFA）と安全境界の承認要否を合わせて判定する。判定結果は`救済可`／`制約付き救済`／`救済不可`の三値とし、根拠ゲート結果を伴わない判定を出さない |
| 13.4 | ワークアラウンドSKILL | 不具合recordから救済候補（FW修正のみ／追加工のみ／併用）を立案し、13.2の差分contractへ落として13.3の再検証を呼び出すSKILL（例: `/acd:workaround`）を追加する。SKILL自体はL2の操舵であり合否権限を持たず、候補と根拠、代替案、不可理由をprovenance付きで返す |
| 13.5 | 作業指示書・検査手順生成 | 対象個体、必要部品・工具、作業手順、該当箇所を強調した視覚投影、作業後の検査項目と期待値を生成する。検査項目は出荷検査文書生成SKILLと同じ知識源（graph・ゲート閾値・FW投影）から導出し、出所のない基準を作らない。生成文書はマイルストーン9のprovenance規則に従い`out/docs/`へ格納する |
| 13.6 | 個体トレーサビリティとWA廃止条件 | どの個体にどのワークアラウンドを適用したかを追跡可能な記録として残し、次revisionで当該不具合が構造的に解消されたことをゲート結果で確認できた時点をWA廃止条件として定義する。ECOワークフロー（マイルストーン20.1）と対応付ける |

13.1〜13.6は計画である。

## マイルストーン14: VibeBB単体成立（会話駆動の設計反復）

汎用エージェントの代行なしで、会話から設計反復を開始し、候補生成・検証・失敗からの
回復までを回せる状態を目指す。L1権限は決定論的ゲートのままとし、不変条件、
fail-closed境界、L1権限の範囲は変更しない。各項目の観測根拠と詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)を正とする。
マイルストーン14〜20は番号順の優先順位ではなくテーマ別の整理であり、優先順位は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)の優先順位節と各節の依存関係に従う。

| 順 | フェーズ | 内容 |
|---|---|---|
| 14.1 | Skill package refのskew解消（H-1〜H-5） | refの陳腐化をCIと`/acd:doctor`で検出し、pinned `acd`をlocked imageへ事前導入して実行時のgit・ネットワーク依存を除く。CIでSkill scriptをfixtureに対し実行し、pinned `acd`でgraphが読めることを検査する。達成 |
| 14.2 | 設計述語の適用条件宣言と機能ブロック契約registry（J-1〜J-3） | 宣言された機能ブロックに対応する述語だけを必須にし、新トポロジの追加を述語コード改変ではなく契約追加で行えるようにする。fab profileを複数持てるようにする。fail-closed境界は維持し、「検証不能」と「機能を持たない」を区別する |
| 14.3 | 失敗理由の構造化とゲートの前倒し評価（B-3、B-4、K-3） | 未配線netとpad対などの失敗理由を機械可読Evidenceとして返し、配置のみで判定できる述語をrouter実行前に評価する。利用者向けに変更可能な次元と現在の余裕を含む形で提示する。達成 |
| 14.4 | 物理設計の自律探索loop（B-1、B-2、B-5〜B-9） | B-1・B-2・B-5〜B-9を達成。配置・回転とGPIO割当のbounded探索loop、placement coupling、単一mechanical datum、stitch via候補fallback、設計自由度の宣言、`stitch_candidate_report`の常時保存を追加した |
| 14.5 | 要件→graphの変換と任意設計fixture（A-1〜A-5、I-2） | 会話由来の要件レコード化、任意設計向けfixtureビルダー、要件差分からgraph差分（接続・FWピン・テストポイント・シルク・rationale）を同時更新するcompiler、部品選定とlibrary provenance、回路トポロジ合成、agent向けtool（FW pipeline、fixture編集、発注、失敗診断）の網羅。機能ブロック契約registryへの宣言入口も追加した。達成 |
| 14.6 | gd1固定の解消と発注laneの汎用化（I-3〜I-5、E-5、C-2〜C-3、D-1〜D-3） | workspace既定値、生成物名・`part_number`、`order_policy`の必須evidence anchor、FW設定をgraph_id・graph宣言由来にする。測定feedback適用、見積provider境界、実発注provider境界までを追加し、GD1以外の設計も同じlaneで扱えるようにする。達成（実supplier接続は境界の後続作業） |
| 14.7 | 実行時間と再開性（E-1〜E-4、E-6、K-1、K-2、K-4） | stage並列化、run並列、JVM・containerの資源宣言、入力hash単位のstage cache、単一orchestrator、途中失敗からの再開、stageごとの所要時間記録を達成した。検証段階の並列実行（E-6）は既存の`pytest -n auto --dist loadgroup`と`verify_all.py --jobs N`を維持し、`uv sync`とfullの後続pipelineはbarrierとして単独実行する。新しいcacheはDSN／SESの生成物だけを対象とし、ゲートとEvidenceは毎回再実行する |
| 14.8 | workspace初期化とbootstrap（G-1〜G-3） | workspace作成からshallow clone・shallow submodule取得・plugin読み込み確認・`/acd:doctor`までを1経路にまとめ、host `uv sync`を廃止した。doctorへworkspace健全性検査（repository不在、submodule初期化、`uv.lock`同期、lock digestのpull可否、FW実行に必要なimage前提）を追加し、会話開始時のbootstrap経路を用意する。達成 |
| 14.9 | image publishとdigest lock更新の自動化（F-1〜F-4） | `publish-acd-images.yml`でtoolsと`acd-server`を単一jobで直列publishし、`skip_tools`によるserver単独再build、lock更新PRの自動作成、lock digestとregistry現行manifestの一致検査、`docker/README.md`の配布記述と実運用の整合を実現する。達成 |
| 14.10 | VibeBB loopのcommand（I-1） | `/acd:vibebb-loop`とgraph駆動の単一orchestratorを追加し、要件からgraph検証、silkscreen barrier、基板・筐体・FW、発注可否までを固定順序でfail-closed実行する。達成 |
| 14.11 | 会話駆動loopの残存不足（L-1〜L-7） | orchestratorの二重化解消（cache・resume・timing・lane並列を会話経路へ接続）、却下後の候補探索の自動連結、要件→graph段のloop内取り込み、order-total生成経路の追加、gd1既定値の残存解消、契約registry・catalogの被覆整理を扱う。L-1〜L-6を達成し、topology templateのdata化（`shared_nets`とscope-awareな一意性）、部品catalogの追加経路、USB-C非搭載／電池給電fixtureの到達性まで実装した。電池の充電・保護回路の規範的契約とpredicateは16.2・16.3依存として本範囲外に置く。L-7の再監査を実施し、残る不足を[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のM節（M-1〜M-6）へ根拠・優先度・依存・完了条件付きで記録した。M-1・M-2は14.12、M-3はマイルストーン7のprovider境界の後続、M-4は16.2・16.3、M-5はマイルストーン5の実機Evidenceへ割り当てる。C-1（筐体の干渉解決探索）はマイルストーン11.5で達成済み、C-4（CPL orientation期待値のfixture非依存化）はマイルストーン7の範囲で達成済みである。達成 |
| 14.12 | 再監査で残った会話駆動loopの不足（M-1・M-2） | 筐体pipelineのfail-closed却下を引き金とした`explore_enclosure_candidates`のloop内自動連結（M-1）と、任意graph向け設計固有検証laneの宣言由来化（M-2）を扱う。探索reportはL2操舵・L3観測のままとし、候補予算とround上限、graph ID・revisionの一致と正規化content hashの変化検査、未宣言を合格としない境界を維持する |
| 14.13 | 実機実測で残った新規設計の不足（N-1〜N-7、N-11） | 実機OpenHands環境でGD1以外の新規設計を投入した実測で残った不足を扱う。`DesignFixtureSpec`へmechanical・silkscreen・firmware moduleの宣言を追加（N-1）、必須宣言のpreflight（N-3）、parts catalog由来のpin function展開（N-5）、Stop hookのfail-closed停止経路（N-2）、rationale coverageの生成主体検査（N-4）、要件↔topology述語（N-6）、設計反復のみのmode（N-7）、生成器による手編集上書きの防止（N-11）。判定と閾値は緩めず、未宣言・unknownを合格へ倒さない |
| 14.14 | 宣言経路解消後の実機実測で残った不足（O-1、O-2、O-4、O-5、O-9〜O-13） | O-1、O-2、O-4、O-5、O-9、O-10、O-11、O-12、O-13を達成。FWはcapability／device registryとgraph sequenceからpinとcodeを導出し、未宣言peripheralを生成しない。筐体laneは設計非依存entrypointと機械preflightを備え、機械ノード・属性・参照・rationale coverageを一括診断する。lane preflightは`declarations_complete`／`declarations_incomplete`とL3診断契約、checked／unchecked predicate集合を記録し、rationale stop hookは対象設計を決定論的に解決する。container起動前は物理メモリ（swapを加算しない）、MemAvailable、CPU、disk、JVM heapをfail-closedで検査し、FreeRoutingの最大heapをhost／container両経路で明示する。残るのはO-12の`QuoteRecord`／`OrderScope`導出、およびO-3、O-6〜O-8の運用整備。判定と閾値は緩めず、timeout・unknown・未宣言を合格へ倒さない |
| 14.15 | Devinなしで新規設計を1周させるための残タスク（P-2〜P-4、Q-1〜Q-10） | 多コアVPS実測（2026-08-30）とその後の復帰経路のコード監査で残った不足を扱う。却下後に設計入力を決定論的に修正して反復する経路をend-to-endで閉じることが本フェーズの目的であり、Q-4（探索後のrationale更新）とQ-5（宣言された上書きによるfixture再生成）を前提として、Q-2・Q-3（会話経路からの起動とremediation由来の候補生成）、Q-1・Q-8（laneごとの復帰次元の宣言）、Q-6・Q-7・Q-9・Q-10（要件差分の拡張、bounded反復harnessの接続、診断入力の拡張、firmware capability registryへの宣言追加経路）へ広げる。設計側の不足としてP-2（初期配置のdecoupling制約）、観測側としてP-3（QEMU打ち切り表示）とP-4（FW laneのauthoritative Evidence）を含む。L1権限、閾値、fail-closed境界は変更しない |
| 14.16 | FW lane専用の候補生成と配置テストの環境依存解消（R-1〜R-3） | FW固有remediationだけを入力とする候補生成器、footprint library非依存の配置回帰、FW復帰の実測記録を扱う |
| 14.17 | 復帰経路と新規設計入口の是正（S-1〜S-5） | 候補評価時のrationale更新、残予算での次候補評価、宣言toolの不在検出、library資材宣言の統一、進行表示を扱う。S-3の配布形態と復帰成立実行の実測は未了 |
| 14.18 | 復帰候補評価からL3観測の混入を除く（T-1〜T-5） | 候補評価の独立timing記録、複数候補の列挙、宣言tool不在のdrift guard、L3 digestの統合、transport失敗時の出力保持を扱う。T-1〜T-5は実装済みで、復帰成立runの実測記録は未取得 |
| 14.19 | 製造提出データの完備とscope改定後の残タスク（U-1〜U-5） | UTF-8明示、STL出力、quote／order例のrevision整合、decoupling配置、製造提出の単一L1判定を扱う。達成 |
| 14.20 | Devin不在で新規設計を1周させるための残関門（V-1、V-3、V-5〜V-7、V-9） | V-1、V-3、V-5、V-6、V-7、V-9を達成。第6回実機実測で残った不足を扱う。新規specの宣言不足をfixture生成段で列挙して具体名で返す（V-6）、container由来資材のhost混入検出（V-1）、L3記録だけで合格を述べさせない報告契約（V-3）、失敗時も判定を変えずに成果物を回収できるdownload経路（V-5）、timing recordへのwall-clock明示（V-7）、宣言tool不在の機械可読記録（V-9） |
| 14.21 | GD1非依存の達成判定（W-1〜W-4） | W-1〜W-4を達成（非GD1 fixture `mini-blink-dongle`がdigest固定containerで全laneとauthoritative Evidence検証を通過）。GD1をregression positive controlとして残したまま、GD1以外の設計だけでVibeBBが1周する状態の達成条件を宣言し、既定値・fixture解決・述語適用・CI authoritative gateのGD1固定を判定可能にする |

不足項目（C、D、L、M、N、O、P、Q、U、V、W）の各フェーズへの割当経緯と14.1〜14.15・14.19の完了条件は[`roadmap-completed.md`](roadmap-completed.md)を正とする。

### 14.16 FW lane専用の候補生成と配置テストの環境依存解消（R-1〜R-3）

14.15で復帰経路は全laneへ連結したが、FW laneの候補生成は基板向け探索の流用であり、
初期配置の決定論的テストはホスト側のKiCad footprint libraryに依存する。本フェーズは
acd-agent単体でのVibeBB 1周を、FW laneと配置解決の両方で回帰可能にすることを目的とする。
`explore_firmware_candidates(...)`は現在`explore_board_candidates(...)`へ委譲しており、
候補評価は基板pipelineの前提（配置・回転次元、基板側remediation）を共有する。そのため
FW固有のremediation（未登録action、pin function不整合、capability宣言不足、QEMU実行の
前提不足）に対して候補を絞り込めず、`gpio_assignment`以外の次元を扱えない。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `explore_firmware_candidates`（現在は`explore_board_candidates`への委譲）、`enumerate_gpio_assignment_candidates`、`contracts/firmware-capability-registry.json`、`contracts/lane-recovery-declaration.json`、`firmware_evidence`のvirtual log検査、`tests/core/test_decoupling_placement.py`のfootprint library skip条件、`docker/image-digests.json`のtools image |
| 実装 | FW lane専用の候補生成器（R-1）: FW pipelineの却下predicateとcapability registryの宣言だけを入力に、`gpio_assignment`とFW設定次元の候補を列挙し、基板側の配置・回転次元を候補に含めない。未登録actionや宣言不足は候補生成ではなく必要宣言のL3提示へ倒す。決定論的配置テストの環境非依存化（R-2）: 初期配置の解と距離判定を、pinned footprint libraryが無いホストでも実行できる固定fixture（pad座標を宣言した最小graph）で回帰させ、実libraryを要するcaseはdigest固定container jobで実行する。FW復帰の実測記録（R-3）: FW laneの却下から復帰までをdigest固定containerで実測し、`vibebb-standalone-verification.md`へround、候補ID、変更subject、再実行laneを追記する |
| 正常系 | FW lane却下（未登録action以外の、宣言済みGPIO代替で解ける却下）から、FW専用候補生成が宣言された次元だけで候補を出し、採用候補に対してFW laneのdeterministic stageを再実行してrevision一致のauthoritative Evidenceを生成する。基板・筐体laneの判定、GD1の判定、正規化hashは変化しない |
| negative・fail-closed | FW固有remediationが無い却下、宣言されていない次元の候補、capability registryに無いactionを前提とする候補、virtual logを欠くEvidence、revision不一致はいずれもfail-closedで停止する。QEMU由来のEvidenceを実機測定として扱わず、探索reportと診断はpass authorityを持たない。環境非依存化したテストは、libraryの有無で判定が変わる経路をskipで隠さず、containerで実行する対象として明示する |
| 再現性 | FW候補の列挙順、候補ID、変更subject、再実行stageを宣言順で固定し、`--jobs 1`と並列で収集件数・判定・正規化hashを一致させる。footprint library非依存fixtureのpad座標と期待距離を固定値として記録し、container側テストと同じ解になることを確認する |

### 14.17 復帰経路と新規設計入口の是正（S-1〜S-5）

14.15の実装後に同じ8コアVPSで実測した結果（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 10節）、
宣言由来のlane復帰planは機能し（`recovery_supported: true`、`recovery_explorer: board`、
`remediation_dimensions: ["component_placement_xy"]`）、生成された候補は`power_decoupling`を
満たす配置へ到達していた。しかし候補の評価がrationale更新前のgraphで行われるため
`rationale coverage failed: missing=18, stale=18`で却下され、`winner_written=false`、
`termination_reason=fail_closed_stop`で復帰が成立しない。さらに新規specからのfixture生成は
部品catalogのlibrary資材宣言と生成fixtureの不一致により最初のstageで停止し、GUI配布形態では
`acd_*` ToolDefinitionが会話へ登録されないためcommandの宣言toolへ到達できない。ゲートは
いずれも正しく閉じており、緩和ではなく経路の是正で解くフェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `exploration`の候補評価経路、`commit_candidate_graph`と`refresh_rationale_document`、`check_rationale_coverage`、`fixture_builder`の`_normalize_decoupling_placement`、`gd1_fixture/components.py`のlibrary宣言、`resolve_fixture_path`、`register_acd_tools()`と`build_acd_conversation()`、ADR-0036のambient install経路、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のS節 |
| 実装 | 候補評価入力へ確定経路と同一のrationale更新を適用する（S-1）、候補固有の却下では残予算で次候補を評価し予算をL3へ明示する（S-2）、ambient install経路の会話へACD tool入口を登録するか宣言toolの不在をfail-closedに検出する（S-3）、catalogのlibrary資材宣言を生成fixtureへの同梱かcontainer内絶対pathへ統一し宣言と生成の両側を検査する（S-4）、L3 timing recordとexploration reportを会話へ返す進行表示（S-5） |
| 正常系 | GD1を摂動した内部整合fixtureに対し`recover_lanes`が候補を確定し、graph IDとrevisionを保持したまま正規化content hashが変化し、rationaleが同一transactionで更新され、基板laneの再実行がL1ゲートを通過する。新規specからのfixture生成がlibrary資材を解決して基板laneへ到達する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | rationale更新不能、graph ID／revisionの不一致、正規化hashの不変、候補予算・round上限の超過、宣言と生成が食い違うlibrary資材、宣言toolの不在はいずれもfail-closedで停止する。候補report、進行表示、GUI観測はpass authorityを持たず、`pass_evidence`はrevision一致したL1ゲート由来に限る |
| 再現性 | 候補ごとの評価入力hash、rationale更新結果、予算消費、再実行したlaneをL3記録として保存し、同一入力での再実行で判定と正規化hashが一致することを回帰テストで固定する。復帰が成立した実行のwall-clockと資源使用を[`operations.md`](operations.md)へ追記する |

S-1とS-4は単体成立の前提であり先に扱う。S-3は配布・登録経路の定義であり、実装だけでは
閉じない。S-2とS-5は予算と進行の可視化である。

S-1、S-2、S-4、S-5とS-3のdrift guard（`scripts/verify_acd_tool_registration.py --command`）は実装済みで、記録は[`roadmap-completed.md`](roadmap-completed.md)にある。S-3の配布形態そのもの（ambient install経路への登録）と復帰成立実行の実測記録は未了である。

### 14.18 復帰候補評価からL3観測の混入を除く（T-1〜T-5）

14.17の実装後に同じ8コアVPSでplugin（`fb286380…`）とlock済みserver image
（`sha256:d683f14b…`）で実測した結果（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 11節）、
S-1は解消し候補はrationale coverageで却下されず決定論的pipelineへ到達した。しかし候補評価が
親laneと同一の`TimingRecorder`を共有するため、pre-router却下で`finish`されずに残った
`board[1/12]`と衝突し、候補はtiming stageの二重開始（`timing stage already started`）を理由に
`gate_rejected`となる。復帰は基板却下後にしか起動しないため衝突は常に
発生し、`winner_written=false`のまま`candidate_pool_exhausted`で終わる。加えて候補生成が1件
（`generated_candidates=1`）しか返さないため候補上限3・round上限2は行使されない。L3観測の失敗を
L1判定へ持ち込まないための是正フェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `src/acd/core/runtime_records.py`の`TimingRecorder`、`src/acd/pipeline/design_loop.py`の候補`pipeline_runner`、`src/acd/core/exploration.py`の候補評価と`_refill_pending`、`plugins/acd/skills/acd-placement-search`の候補生成、`scripts/report_progress.py`、`src/acd/openhands/workspace.py`の`_execute_and_download()`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のT節 |
| 実装 | 候補評価へ親と独立したtiming記録（または候補IDでnamespaceしたstage名）を与える（T-1）、観測起因の例外を`gate_rejected`と区別する（T-1）、remediation次元ごとに複数候補を宣言順で列挙する（T-2）、pinned SDK v1.44.1のplugin形式（`vendor/software-agent-sdk/openhands-sdk/openhands/sdk/plugin/`）にToolDefinition登録面がないため、ambient経路ではcommandが宣言toolの不在をfail-closedに検出し決定論的CLIへ倒すdrift guardをfast段で実行する（T-3）、`failure_reason`と`next_step_action`をL3 digestへ取り込む（T-4）、transport失敗時もcommandのexit code・stdout・stderr・失敗種別を出力してから非ゼロ終了する（T-5） |
| 正常系 | GD1を摂動した内部整合fixtureに対し`recover_lanes`が候補を確定し（`winner_written=true`）、graph IDとrevisionを保持したまま正規化content hashが変化し、rationaleが同一transactionで更新され、基板laneの再実行がL1ゲートを通過する。候補生成は上限まで候補を返し、`consumed_budget`と`remaining_budget`が実行と一致する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | timing記録の破損・欠落、候補評価の例外、graph ID／revisionの不一致、正規化hashの不変、予算・round上限の超過はいずれもfail-closedで停止する。観測層（timing、digest、探索report）の成功はpass authorityを持たず、`pass_evidence`はrevision一致したL1ゲート由来に限る |
| 再現性 | 候補ごとの評価入力hash、timing記録の帰属、予算消費、再実行したlaneをL3記録として保存し、親laneが却下で中断した後に候補評価が成立することを回帰テストで固定する。復帰が成立した実行のwall-clockと資源使用を[`operations.md`](operations.md)へ追記する |

T-1〜T-5は実装済みで、記録は[`roadmap-completed.md`](roadmap-completed.md)にある。実機で成功した復帰runのwall-clock記録は未取得である。

T-1は復帰経路の唯一の停止点であり先に扱う。T-2はT-1解消後に予算を意味あるものにする前提、
T-4は表示の統合、T-3はS-3の未了部分と同一の配布形態の論点、T-5は検証作業の可読性である。
いずれもEvidenceの合否権限とfail-closed境界を変更しない。

### 14.20 Devin不在で新規設計を1周させるための残関門（V-1、V-3、V-5〜V-7、V-9）

第6回実機実測（2026-08-31、新規VPS・新規workspace、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 13節）で、GD1は
決定論的経路で端から端まで通過した。残る停止点は新規設計側にある。新規specからのfixture生成は
成功するが、`silkscreen-resolve`が`GraphExtractionError: silkscreen declarations are missing`で
fail-closedし、返る`next_step_action`は「graphを調整して再実行せよ」であって、
specへ何を追記すればよいかを示さない。宣言の受け口自体は
`DesignFixtureSpec.silk_texts`／`silk_graphics`として存在し、必要属性も
`lane_preflight`の`LANE_REQUIREMENTS["silkscreen-resolve"]`に宣言済みだが、loopはこの
preflightを実行しないため、不足は実行の途中でしか判明しない。ゲートは正しく閉じており、
緩和ではなく不足宣言の提示で解くフェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `src/acd/core/silkscreen.py`の`GraphExtractionError`、`src/acd/core/lane_preflight.py`の`LANE_REQUIREMENTS`と`run_lane_preflight`、`src/acd/pipeline/fixture_builder.py`の`silk_texts`／`silk_graphics`投影、`scripts/run_design_loop.py`、`src/acd/openhands/workspace.py`の`_execute_and_download()`、`src/acd/core/runtime_records.py`の`TimingRecorder`、`scripts/verify_acd_tool_registration.py`、`plugins/acd/commands/vibebb-loop.md`、`plugins/acd/hooks`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のV節、[`examples/golden-design-1-vps-20260901/report/improvement-notes.md`](../examples/golden-design-1-vps-20260901/report/improvement-notes.md)（同メモのD-1〜D-4はV-7〜V-10と読み替える） |
| 実装 | fixture生成とloop入口で実行予定laneの`run_lane_preflight`を評価し、不足するnode kind・node数・属性名を列挙して`next_step_action`へ「specへ追加すべき宣言」を具体名で返す（V-6）。silkscreen laneでは`mechanical.silk_text`の`layer`／`role`／`text`／`stroke_width_mm`／`height_mm`／`placement_basis`／`placement_search_order`／`placement_reference`を名指しする。宣言の自動補完は行わない。containerからhostへEDA資材を取り出す操作をhookで拒否するか、host実行時にcontainer由来資材の混在を検出してprovisional扱いを記録する（V-1）。commandの報告契約へauthoritative Evidence検証の実行と結果提示を必須項目として書き、`report_progress.py`のdigestへEvidence未検証を明示する行を持たせる（V-3）。`_execute_and_download()`が非ゼロ終了時も宣言済みdownloadを試み、判定はcontainerのexit codeで維持する（V-5）。timing recordへstage duration合計と区別できる`wall_clock_seconds`を持たせる（V-7）。`verify_acd_tool_registration.py --command`の結果を機械可読JSONとしてworkspaceへ保存する（V-9） |
| 正常系 | silkscreen宣言を備えた新規specが、fixture生成からsilkscreen barrierを越えて基板laneへ到達する。宣言が欠けたspecは実行前に`declarations_incomplete`で停止し、不足宣言名と追記先を返す。fail-closedで終わったcontainer実行からも成果物を回収でき、runnerのexit codeは非ゼロのままである。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | 不足宣言の列挙、進行表示、tool登録記録はいずれもL3観測であり合格側権限を持たない。preflightの`declarations_complete`はlane通過を意味しない。downloadの成功をcommand成功として扱わず、部分downloadを合格へ倒さない。container由来資材が混在したhost実行のEvidenceをauthoritativeへ昇格しない。宣言の自動補完、既定値の暗黙適用、閾値・ゲート条件の緩和は行わない |
| 再現性 | preflight結果、不足宣言名、download結果、wall-clockとstage duration合計、tool登録差分をL3記録として保存し、同一入力での再実行で一致することを回帰テストで固定する。fail-closed runからの成果物回収を、tarとexit 0による回避策なしで再現する |

実装状況: V-6（`lane-preflight` stageと`fixture-generation`のpreflight診断、
`missing_declarations`と`next_step_action`）、V-7（`wall_clock_seconds`と
`stage_duration_sum_seconds`の分離）、V-5（非ゼロ終了時のdownload試行と`download_errors`、
exit code維持）、V-9（`out/tool-availability/<command名>.json`）、V-3（commandの報告契約と
digestの`authoritative_evidence: unverified`）は達成した。詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のV節の実装状況を正とする。V-1は未着手である。

V-6は新規設計入口の唯一の停止点であり最優先で扱う。V-3とV-9は、会話経路がL3記録だけで
合格を述べないための報告契約と一次資料であり同順で扱う。V-5とV-7は検証可能性、
V-1は防御の深さである。V-2（GUIのplugin picker）はOpenHands側の課題であり、本リポジトリの
実装対象外として記録だけを残す。V-4、V-8、V-10は運用・手順の整備として15.17〜15.19で扱う。

### 14.21 GD1非依存の達成判定（W-1〜W-4）

GD1は回帰のpositive controlとして今後も維持する。本フェーズの目的はGD1の削除ではなく、
「GD1だけが全ゲートを通る設計である」状態の解消を判定可能にすることである。14.6でGD1固定の
命名・FW設定・policy参照は宣言由来へ一般化し、14.2で述語の適用条件を機能ブロック宣言へ
移した。非GD1 fixture `fixtures/mini-blink-dongle/`はdigest固定container（`run_in_workspace.py`）で
silkscreen、基板、筐体、FW、製造提出判定、`verify_authoritative_evidence.py`を通過し、W-1〜W-4は達成した。
GD1参照の棚卸しは`contracts/gd1-reference-inventory.json`と`scripts/verify_gd1_references.py --check`で
driftとして検出する。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `fixtures/golden-design-1/`、`src/acd/pipeline/gd1_fixture/`、`scripts/build_gd1_fixture.py`、`scripts/run_gd1_pipeline.py`、`src/acd/core/naming.py`、`src/acd/core/design_predicates.py`の`PREDICATE_CATALOG`と適用条件宣言、`plugins/acd/hooks/order-policy.json`、`.github/workflows`の`container-gates`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のW節 |
| 実装 | GD1以外の設計を1件、宣言完備のfixtureとして追加し、要件検証からsilkscreen、基板、筐体、FW、製造提出判定までをdigest固定containerで通す（W-1）。既定fixture・既定出力名・既定policyがGD1へ解決される経路を洗い出し、graph_idと宣言由来へ置換する。positive control用途で残す参照は用途を明示宣言する（W-2）。設計述語の適用条件が機能ブロック宣言だけで決まり、GD1固有のnet名・refdesを前提とする分岐が残っていないことを検査する（W-3）。CIの`container-gates`へ非GD1設計のlaneを追加し、GD1と同じ判定基準でauthoritative Evidenceを検証する（W-4） |
| 正常系 | 非GD1設計だけでVibeBBの1周（要件→設計→ゲート→製造提出判定→authoritative Evidence）が成立し、GD1固有の既定値へfallbackせずに完了する。GD1のlaneも従来どおり通過し、判定・Evidence・正規化hashは変化しない |
| negative・fail-closed | 非GD1設計の宣言不足はfail-closedで停止し、GD1の既定値・既定fixture・既定命名へ暗黙にfallbackしない。GD1固有の前提を残す述語分岐、用途宣言のないGD1参照、非GD1 laneを持たないCI構成はいずれも未達として扱う。positive controlの通過をもって非GD1設計の合格としない |
| 再現性 | 非GD1設計のwall-clockと資源使用を[`operations.md`](operations.md)へ記録し、CIで両設計の判定と正規化hashを固定する。GD1参照の棚卸し結果を機械可読な一覧として保存し、追加参照をdriftとして検出する |

W-1は14.20のV-6解消を前提とし、W-3は14.2、W-4は6.4のCI移行を前提とする。W-1〜W-4を
満たした時点で「GD1が無くても新規設計をVibeBBできる」状態に到達したと判定する。GD1 fixtureは
その後もregression用のpositive controlとして維持し、削除は行わない。

### 14.22 自然文のみ新規設計の実機不合格からの残関門（Y-*）

第8回実機実測（2026-09-06、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 15節）では、
自然文要件のみをGUI会話へ投入し、GD1とは無関係の新規設計`dual-beacon-tag`をagentが自力で
spec生成から走らせた。結果は`board-pipeline`のrouter非収束（探索`exhausted`）と
enclosure laneの`face: right`未対応でfail-closedし、authoritative Evidenceはfirmware
1件のみで検証は`FAIL: required lane Evidence missing: electrical`であった。pristine
`e45f1ec`の対照runが同一の壁を再現したため、会話内のagentの`src/`改変は荷重を持たず、
壁はmain側の未解消である。本フェーズは閾値やゲートを緩めるのではなく、診断面と
provenance・契約の不足を閉じる。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `src/acd/pipeline/design_loop.py`（`loop-summary`）、`src/acd/adapters/freerouting/`、`src/acd/adapters/cad/project.py`の`face`判定、`plugins/acd/skills/acd-firmware-esp32c3/scripts/fw_project.py`と`contracts/firmware-capability-registry.json`、`src/acd/openhands/evidence/git.py`の`is_design_input`と`order_gate.py`、`src/acd/schema/tool_envelope.py`、`scripts/verify_authoritative_evidence.py`、`src/acd/pipeline/fixture_builder.py`、`plugins/acd/hooks`のprojection保護、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のY節、[`examples/dual-beacon-tag-vps-20260906/`](../examples/dual-beacon-tag-vps-20260906/) |
| 実装 | router非収束時に`loop-summary`へunrouted数・収束状態・主要な未解決netをL3診断として記録する（Y-8、解消済み。board-pipeline／board-exploration失敗時の`router_diagnostics`と候補別`candidate_router_diagnostics`、plateau・減少継続・timeoutで分岐した`next_step_action`追記）。enclosure laneが`front`・`back`・`left`・`right`の開口faceを受理し、受理しないfaceを契約とpreflight（`mechanical.connector_opening.face_unsupported`）で明示してfail-closedを前倒しする（筐体の壁、解消済み）。FW capability契約へ複数LEDと入力pin roleを追加するか、追加するまで要件→`fw.sequence`被覆検査で要件の削除をfail-closedにする（Y-6・Y-11）。Evidence provenanceへsource-treeのgit SHAとdirty digestを記録し、`verify_authoritative_evidence.py`がdirty sourceをfail-closedで拒否する（Y-10）。container内KiCad資材からsymbol・footprint sha256を採取するlibrary hash helper（Y-3、解消済み。`scripts/pin_library_hashes.py`がspecへdigestを採取・記入する）。`FixtureBuilderError`へcoverage要約（missing／stale／unclassified）を含める（Y-2、解消済み。coverage要約を`FixtureBuilderError`と`rationale coverage failed`へ付与）。projection保護hookのmatcherを狭め、empty poll・読み取り系commandを止めない（N-3・N-6・N-8、解消済み。empty poll・read-only command・読み取り系inline code・heredocのdata本文は許可し、`mv`の元pathとshell／interpreter heredoc本文は引き続き拒否する）。`safety_boundary`等のenum許容値をspec文書とpreflightへ出す（Y-5、解消済み。`src/acd/core/declaration_vocabulary.py`が許容値の単一の正となり、`lane-preflight`が`unsupported_values` codeでfail-closed報告する）。silkscreen resolverの未宣言positionを前段で検出する（Y-7、解消済み。resolver結果が`resolved`以外の場合に未解決text名を挙げてfail-closedとする）。decoupling_targetの多ピン対象の意味を文書化する（Y-9、解消済み。同一電源netを複数padで共有する対象は自然順最小padへ決定論的に解決し、候補を配置出力へ記録する） |
| 正常系 | 診断・provenance・契約が揃った状態で、自然文のみから生成した新規設計が同じ壁に達しても、停止理由が`loop-summary`とEvidence provenanceから第三者が読み取れる |
| negative・fail-closed | dirty sourceからのEvidence、要件を落とした`fw.sequence`、未宣言の非対応face（`front`・`back`・`left`・`right`以外）、hash placeholderはいずれもfail-closedのままである。診断・provenance・helperはL3観測であり合格側権限を持たない |
| 再現性 | 追加する診断値とprovenanceフィールドをL3記録として保存し、同一入力での再実行で一致することを回帰テストで固定する |

実装状況: Y-1（`--design-only`を指すエラーメッセージと`vibebb-loop.md`のdesign-only運用
記載）とY-4（`strapping_pin`を宣言済み全`led_drive_net`へ一般化、negative test込み）は
`devin/1788725512-vibebb-dual-beacon-repair`（commit `71f0885`）で解消した。Y-10は
`devin/1788735996-evidence-source-provenance`（PR #337）で解消した。ToolEnvelopeへ
`source_revision`・`source_tree_state`・`source_dirty_digest`を追加し、runnerは
source tree（`src`・`scripts`・`plugins`・`contracts`・`libraries`・`docker`・
`pyproject.toml`・`uv.lock`）のgit provenanceを`ACD_SOURCE_*`環境変数でcontainerへ
forwardする。dirty／非gitの`--repo`は`--allow-dirty`無しでcontainer起動前に拒否し、
`verify_authoritative_evidence.py`はprovenance欠落・`unknown`・非`clean`をfail-closedで
拒否する。`--source bundled`はprovenanceが`unknown`となりそのEvidenceはverifierを
通過できない。Y-6は`devin/1788737805-fw-requirement-coverage`（PR #338）で、
要件→`fw.sequence`被覆検査（`check_firmware_coverage`、FW lane起動前の
fail-closed停止と`firmware-coverage.json`／preflight `firmware_coverage`診断、
registryへの`emits_triggers`追加）として解消した。Y-11はPR #340で、pin role
`led2`・`button`と`led2_blink`（第2 LED逆位相点滅）・`button_input`（`button_pressed`発火、
active-low入力で点滅pause／resume）capabilityの登録と`fw_project.py`の射影として解消した。
Y-8は本branch（`devin/1788741004-router-diagnostics-loop-summary`）で
解消し、board-pipeline／board-exploration失敗時に`read_router_diagnostics`が
`l3/router-pass-progress.json`と`gate-evidence/routing-connectivity.json`を読んで
`loop-summary`へ`router_diagnostics`（収束状態・`unrouted`推移・plateau pass数・
fail状態netの一覧）と候補別`candidate_router_diagnostics`をL3記録として載せ、
plateau・減少継続・timeoutに応じた次手を`next_step_action`へ追記する。
ゲート・閾値・passの意味は変更していない。
dual-beacon-tagのend-to-end合格はrouter非収束と筐体faceの壁が残るため未実証である。
筐体face契約は本branch（`devin/1788741768-enclosure-opening-faces`）で
`front`・`back`・`left`・`right`の受理と
`mechanical.connector_opening.face_unsupported`のpreflight前倒しで解消した。
Y-2（coverage要約）とY-7（silkscreen resolverのfail-closed前倒し）は
本branch（`devin/1788742972-silk-resolve-fail-closed-coverage-summary`）で解消した。
Y-3は本branch（`devin/1788743477-pin-library-hashes`）で`scripts/pin_library_hashes.py`として解消した。
Y-5（宣言語彙の単一の正と`lane-preflight`の`unsupported_values`）と
Y-9（decoupling多pad対象の決定論的解決）は本branch
（`devin/1788744113-declaration-vocabulary`）で解消した。
これでhook matcherを含む全項目解消である。fail-closed境界の堅持に直結するものを先に扱った。詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のY節を正とする。

### 14.23 14.22反映後の同一要件再検証（第9回）で残った関門（Z-*）

第9回実機実測（2026-09-07、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 16節）では、
14.22を反映した`main`（`180b628`）と更新済みimageのもとで第8回と同一文言の自然文要件を
投入した。Y-2・Y-3・Y-6・Y-7・Y-8・Y-10・Y-11とhook matcherの効果は観測でき、
order-total捏造とLED2／ボタン要件の削除は再発しなかった。しかしagentは停止境界ごとに
`src/`編集→commit（provenanceは「clean」のままrevisionが逸脱）、`run_in_workspace.py`の
既定download失敗を契機とした生`docker run`（provenance `unknown`）、`base64`難読化による
matcher回避、`net.en`削除へ倒れ、pristine `180b628`の対照runではagent最終入力が
rationale coverageで停止した。authoritative Evidenceはfirmware laneのみで、検証は
`FAIL: required lane Evidence missing: electrical`（終了コード1）、判定は不合格である。
本フェーズはゲートを緩めず、agentが正規経路に留まれる面（runner・診断文・provenance照合・
matcher）を閉じる。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `scripts/run_in_workspace.py`、`scripts/verify_authoritative_evidence.py`、`src/acd/pipeline/fixture_builder.py`（coverage診断文）、`plugins/acd/hooks/scripts/protect_projections.py`・`session_start.py`・stop policy、`plugins/acd/commands/init.md`、`src/acd/pipeline/design_loop.py`の`lane-preflight`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のZ節、[`examples/dual-beacon-tag-vps-20260907/`](../examples/dual-beacon-tag-vps-20260907/) |
| 実装 | source provenanceの`ACD_SOURCE_GIT_SHA`をbootstrap record／installed plugin revision／`--source-revision`と照合し不一致をfail-closedにする（Z-3）。`run_in_workspace.py`の既定downloadを既定command・`--graph`明示時に限定し、任意commandでは`--download`指定分だけを扱う（Z-5）。hookが`acd-server`／`acd-tools` imageの生`docker run`／`docker exec`起動を拒否しrunner経由を案内する（Z-11）。coverage診断の会話向けnext stepから source表名を外し設計入力側の次手だけを示す（Z-2）。deny理由へ判定種別と該当tokenを付ける（Z-4）。inline codeの動的実行token（`exec(`・`eval(`・`base64.b64decode(`等）を拒否し（Z-6）、wrapper command越しの内側commandを同じ規則で再帰評価する（Z-7）。`init.md`の起動例とtimeout手順（Z-1）、最終報告のsource変更節を`git log <bootstrap>..HEAD --stat`の機械出力に固定（Z-8）、宣言側evidence属性の実測record解決検査（Z-9）、`lane-preflight`へmechanical preflight述語の取り込み（Z-10）、SessionStart hookのlock探索（Z-12）。`design_loop.py --fixture-spec`の`spec_dir`伝播（Z-13）は本変更で解消済み |
| 正常系 | 自然文のみから生成した新規設計が停止境界に達したとき、agentが`run_in_workspace.py`と宣言経路だけで次手を取れ、source編集・生container・難読化に倒れない。停止理由と到達段が`loop-summary`とprovenanceから第三者に読み取れる |
| negative・fail-closed | bootstrapから逸脱したrevision、`unknown` provenance、`base64`難読化のinline code、生`docker run`起動、要件を落とした宣言はいずれもfail-closedのままである。診断・matcher・照合はL2／L3であり合格側権限を持たない |
| 再現性 | 対照run（pristine main・同digest）を同一fixtureで再実行し、到達段・失敗理由・firmware Evidenceのprovenanceが一致することを記録する |

実装状況: Z-13（`design_loop.py`の`spec_dir`伝播、回帰テスト込み）はPR #359で解消した。
Z-5・Z-3（runnerの既定download限定、bootstrap revision照合をrunner・verifier・stop policyへ）は
PR #360、Z-4・Z-6・Z-7・Z-11・Z-12（hookのdeny理由・動的実行拒否・wrapper再帰・raw acd image拒否・
SessionStart lock探索）はPR #361、Z-1・Z-2・Z-10（init手順と進行log、coverage診断文、
enclosure lane preflightへのmechanical述語取り込み）はPR #362で実装した。
Z-9（宣言側evidence属性の実測record解決検査、`evidence.declaration`述語）はPR #365、
Z-8（`scripts/report_final_basis.py`による最終報告のsource変更節・設計値節の機械生成と
`/acd:vibebb-loop` step 8の報告契約）はPR #366で実装した。詳細は[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のZ節を正とする。

### 14.24 14.23反映後の同一要件再検証（第10回）で残った関門（AA-*）

第10回実機実測（2026-09-08、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 17節）では、
14.23を反映した`main`（`5bf2c90`）と更新済みimage（server `sha256:fb236ff5…`）のもとで
第8回・第9回と同一文言の自然文要件を投入した。agentは`run_in_workspace.py`＋宣言経路に
ほぼ留まり（生`docker run`はZ-11で1回拒否、gate緩和・script複製・難読化・commitは無し）、
Z-1・Z-2・Z-4・Z-5・Z-9・Z-10・Z-11・Z-13の作動を確認し、routerは収束した
（`final_unrouted 0`）。一方で`contracts/parts-catalog.json`へのentry追加と
`src/acd/core/part_selection.py`のmessage編集が未commitのまま`--allow-dirty`で通り、
最終報告はそれを「pipelineの自動登録」と説明した。停止点はU2のCPL rotation宣言
（mini-blink由来180°）と実測recordの不一致で、pristine対照run（agent最終graph）も同一理由で
停止し、specからの再生成はcatalog不一致でfixture-generationに戻る。authoritative Evidenceは
3 laneとも無く、検証は`FAIL: no Evidence files supplied`（終了コード1）、判定は不合格である。
本フェーズはゲートを緩めず、契約変更が会話内の未commit編集で通る面とbootstrap不在の面を閉じる。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `scripts/run_in_workspace.py`（`--allow-dirty`の範囲）、`src/acd/pipeline/design_loop.py`・`lane_preflight.py`（catalog／registry hash照合、functional block・pin role診断）、`src/acd/core/part_selection.py`（message）、`src/acd/core/evidence_declarations.py`（他fixture転記のL3警告）、`scripts/report_final_basis.py`とstop policy（bootstrap record不在・変更fileの変更action引用）、`plugins/acd/commands/vibebb-loop.md`、`plugins/acd/hooks/scripts/session_start.py`（registry探索）、`fixtures/mini-blink-dongle/spec.json`（AA-1）、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のAA節、[`examples/dual-beacon-tag-vps-20260908/`](../examples/dual-beacon-tag-vps-20260908/)、`src/acd/pipeline/gd1_board.py`・`src/acd/adapters/kicad/`（CPL／DFM／島・DRC診断文）、`plugins/acd/skills/acd-contracts/`・`acd-placement-search/`・`acd-silkscreen-placement/`（Skill手順）、`scripts/fetch_lcsc_footprint_orientation.py`（record取得）、`src/acd/pipeline/gd1_board.py`の`hashes.json`生成と`src/acd/pipeline/theme_song.py`（投影形式検査）、`src/acd/pipeline/design_loop.py`・`scripts/run_design_loop.py`（文書lane・製造提出verdict・PNG rasterの投影段組み込み）、`plugins/acd/skills/acd-product-docs/scripts/`（`generate_instruction_manual.py`の必須macro集合）、`src/acd/pipeline/visual_projection.py`（`derive_png_visual_projections`）、`plugins/acd/skills/acd-theme-song/scripts/theme_song.py`（`Score`→MML render） |
| 実装 | `--allow-dirty`の許容範囲を設計入力path（`fixtures/`・`evidence/`・`out/`）に限り、`src/`・`contracts/`・`scripts/`・`plugins/`のdirtyはfail-closedのまま（AA-5）。graphの`parts_catalog_sha256`・registry hashをcheckout上の契約と照合し不一致を`contract.hash_mismatch`で止める（AA-8）。`vibebb-loop.md`でbootstrap recordの所在確認を必須にし、stop policyがrecord不在を`bootstrap_record_missing`として停止報告へ載せる（AA-3）。`PartSelectionError`へ要求内容と次手を含める（AA-4）。未知functional blockの診断へ登録名一覧を添え、要件文書がLED・I2C pull-upを含むのにblock未宣言なら`requirement.block_missing`で止める（AA-6）。firmware pin roleをgraphのI2C接続から導出する宣言経路（AA-7）。`estimated` evidenceの他fixture転記をL3警告で列挙（AA-9）。報告契約でworktree各entryへ変更actionの引用を必須にする（AA-10）。SessionStart hookがworkspace registryのlockを探索（AA-2）。W-1 fixtureの宣言を実測へ揃える（AA-1、別PR）。修正後run（[`examples/dual-beacon-tag-vps-20260908/fixed-run/`](../examples/dual-beacon-tag-vps-20260908/fixed-run/README.md)、AA-11〜AA-14の実測根拠）で観測した宣言〜出力の乖離も同フェーズで扱う: `_copper_zone`が`min_island_area`をemitせず宣言値が充填後検証専用である点を区別する（AA-11）。CPL basis段でrecordの`Manufacturer Part`／packageと宣言`mpn`の整合を検査する（AA-12）。`part_request`無し部品へも`cpl_rotation_evidence_revision`を補完または欠如属性を診断へ示す（AA-13）。silkscreen resolverが`measured_pass`でも未配置テキストの配置探索を行う（AA-14）。修正後runでDevinが人手で越えた境界（17.12、AA-15〜AA-22）も同フェーズで扱う: CPL rotation診断へ宣言／有効／実測offsetとbasisを併記（AA-15）、LCSC番号無し部品の`FabOutputError`へ`not_fitted`の次手（AA-16）、`vibebb-loop.md`でgraph直接編集を禁止しspec→`--fixture-spec --fixture-overwrite`再生成を必須化（AA-17）、DFM pad-to-edge診断へ最小移動量（AA-18）、GND島・DRC診断へ囲みfootprintと候補レバーを列挙し`acd-placement-search`へ島解消手順（AA-19）、silkscreen診断へ短縮／探索範囲の次手（AA-20）、catalog entry追加の宣言経路とcontainer内hash算出（AA-21）、宣言直後のLCSC record取得とmpn照合手順（AA-22）。投影段の直後にwriterと独立したreader（SMF parser、STEP header/footer、3MF zip CRC・model XML、RS-274X／Excellon終端）による形式検査を置き、結果を`hashes.json`の各entryへ`format_check`として記録、parse失敗はその投影を欠落としてfail-closedにする（AA-23。利用者報告の`theme-song.mid`破損は修正後runの全投影を事後検査して再現せず、生成物側から判別できない点を閉じる）。acd-agentが持つ投影のうちloopが呼ばない3種（`acd-product-docs`の製品説明README・取扱説明書、`verify_manufacturing_submission.py`の製造提出verdict、`derive_png_visual_projections`のPNG raster）を`run_design_loop.py`の投影段へ組み込み、3 lane完了後に同一out root配下（`docs/`・`manufacturing-submission.json`・`visual/png/`）へ生成して`hashes.json`とloop-summaryへ登録する（AA-24。`--design-only`でも実行し、order lane入力は要求しない）。`generate_instruction_manual.py`がGD1固有のmacro集合（`ACD_PIN_UART_*`・`ACD_PIN_USB_*`・`ACD_SHT40_I2C_ADDRESS`・`ACD_LOG_PERIOD_MS`）を必須とする点を、graphのfirmware capability・pin role宣言から必要節を導出する構成へ改め、宣言に無い節は書かずに省略理由を文書へ記す（AA-25。推定値は書かず、宣言もmacroも無い項目はfail-closedのまま）。theme-songの投影にMML（Music Macro Language、テキスト楽譜）を追加し、`render_midi`と同じ`Score`（tempo・拍子・track別note/rest・drum）から`theme-song.mml`を決定論的にrenderして`theme-song.mid`と並べて`hashes.json`・provenance（同一proposal hash）へ登録する。MMLはtrack別channel・`t`（tempo）・`o`/`l`/音長・`r`（rest）・タイの表記を持つ方言を1つ固定し、MML→note列の独立parserで再読込してMIDIのnote数・総tick・pitch列と一致することを検査する（AA-26。不一致はMML投影をfail-closedで欠落にし、MIDI側の合否や3 lane判定へ作用させない。Evidence・fab packageには含めない） |
| 正常系 | 自然文のみから生成した新規設計が停止境界に達したとき、agentが契約変更を会話内の未commit編集で通せず、bootstrap recordのあるworkspaceで`run_in_workspace.py`と宣言経路だけで次手を取れる。到達段がpristine mainの契約だけで再現でき、`loop-summary`とprovenanceから第三者に読み取れる |
| negative・fail-closed | `src/`・`contracts/`がdirtyなcheckout、契約hash不一致のgraph、bootstrap record不在、未実測evidence宣言、要件を落とした宣言はいずれもfail-closedのままである。診断・警告・照合はL2／L3であり合格側権限を持たない。投影の形式検査はchunk長や終端を故意に壊した投影を欠落として止め、検査OKをEvidenceへ昇格しない。文書lane・製造提出verdict・PNG rasterの組み込みはL3投影の追加であり、その失敗はloop-summaryへ欠落として記録するがEvidenceや3 laneの判定を変えず、成功を合格側へ作用させない |
| 再現性 | 対照run（pristine main・同digest）をagent最終specからの再生成（`--fixture-spec --fixture-overwrite`）で再実行し、到達段・失敗理由がGUI経路と一致することを記録する |

実装状況: AA-5は実装済み（dirtyなsource treeは`--allow-dirty`でも拒否）、AA-7は実装済み（firmware pinのnet idから導出するroleをregistry照合し未登録roleを候補付きでfail-closedにする）、AA-8は実装済み（graphの`parts_catalog_sha256`をcheckoutの契約と照合し`contract.hash_mismatch`で停止）。詳細は[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のAA節を正とする。

## マイルストーン15: 運用と文書の整備

運用・文書側の改善項目を出所とする整備を行う。いずれも契約の緩和ではなく、
現行の閾値、ゲート挙動、fail-closed境界を維持する。他フェーズに依存しない運用整備である。

| 順 | フェーズ | 内容 |
|---|---|---|
| 15.1 | ToolEnvelopeの`exit_code`のツール別意味論の文書化 | kicad-cli ERC/DRCは違反件数由来で非ゼロになりうることを記録し、statusと混同しない説明を追加する |
| 15.2 | order-readiness `ready`の定義へのCPL実装基準の明示 | position/rotation basisについてfab側目視確認を前提とすることをreadyの定義へ明記する |
| 15.3 | OpenHands Local GUI APIのトークン発行手順のdocs化 | トンネル越しcurlがUnauthorizedとなる制約を踏まえ、自動化検証に必要なGUI経由のトークン取得手順を記録する |
| 15.4 | リリース手順のdocs化 | タグ作成権限・ruleset、GH013時の対応、実行例リンク中心のリリースノート、Release assetsを添付しない方針を運用手順へ記録する |
| 15.5 | pipelineログの要約出力（入力トークン削減） | pipelineログのtail既定化など、再取り込み量を削減してトークン消費を下げる要約出力を実装する |
| 15.6 | hook遮断理由の要約自動集計 | `RejectionSummary`契約でhookの遮断理由を集計し、遮断の再発箇所を利用者が追える形で提示する。要約はL3観測であり、遮断そのものの判定を置き換えない |
| 15.7 | SKILL triggerとToolDefinition登録条件のdoctor診断 | `ToolRegistrationManifest`契約と`scripts/verify_acd_tool_registration.py`で登録面を固定し、trigger不一致・未登録tool・登録条件不成立を`/acd:doctor`から診断する |
| 15.8 | host EDA不在時の推奨経路への誘導 | host EDA（kicad-cli等）が無い環境では、digest固定locked imageと`DockerWorkspace`経路をdoctorから提示する。host経路をprovisional専用とする境界は変更しない |
| 15.9 | FW実行のhost前提とlocked image同梱のdocs化 | ESP-IDF、Espressif QEMU、`libslirp0`、SDL2系共有ライブラリ、PATH解決の前提を運用手順へ記録し、locked tools imageへの同梱状況を明記する |
| 15.10 | out-rootのhost／container分離と権限起因失敗の区別（N-8） | root実行containerとhost実行が同一out-rootを共用した際の`Permission denied`を、設計起因のfail-closedと区別可能な形で扱う。out-rootの分離、または`--user`と書き込み可能な`UV_CACHE_DIR`／`HOME`の付与を既定にする |
| 15.11 | lane scriptのCLI引数統一（N-9） | `run_fw_pipeline.py`が`--graph`を受け付けない等の不統一を解消し、`--fixture`＋`--out`へ揃える。旧引数は明示エラーで案内する |
| 15.12 | graph単体検証入口の明確化（N-10） | 存在しない`scripts/validate_design_graph.py`への案内を解消し、graph検証の正規経路（preflightまたはlane入口検査）を`docs/`へ明記する |
| 15.13 | 実機実行記録の持ち出し経路（N-12） | 実行記録から公開可能な最小集合を収集する入口を用意し、ホスト名・エンドポイント・ユーザー名の秘匿化を既定にする。秘匿化漏れの検出をnegative testで固定する |
| 15.14 | 長時間laneのbackground実行手順とlog契約（O-3） | 長時間laneをbackground＋logで実行し、同時に1本だけ起動してtail／grepで確認する手順を`docs/operations.md`へ明記する。log先頭へimage digest・revision・コマンド行を必ず記録する |
| 15.15 | doctor出力のauthoritative／provisional分離と次手順提示（O-6・O-7） | doctor出力をauthoritative経路（image digest一致、docker実行可否、ホスト資源）とprovisional経路（host toolchain）へ分離し、lock済みimage未取得時にdigest固定のpullコマンド行を提示する（実行はしない）。分離は表示の分類に留め、fail-closedの範囲を変えない |
| 15.16 | 収集入口へのlane log取り込み（O-8） | `scripts/export_execution_records.py`の入力へlane logを加え、log先頭のimage digest・revision・コマンド行とexit codeを構造化して取り込む。既存の秘匿化と漏洩検出をそのまま適用し、リモートworkspaceからの取得手順を`docs/operations.md`へ明記する |
| 15.17 | 例示commandとfixture有効期間の整合検査（V-4） | `docs/operations.md`のGD1発注集計例の`--evaluated-at`を対象quoteの有効期間内へ揃え、例示とfixtureの期限整合をdocs検証で機械的に固定する。quoteの有効期限や期限検査の閾値は緩めない |
| 15.18 | 資源計測ラッパのscript化（V-8） | 検証のたびに使い捨てのshell scriptを書く状態を解消し、checkout path、image digest、download対象、計測間隔を引数で受ける計測wrapperをrepository内へ置く。計測結果はL3観測であり合否権限を持たない |
| 15.19 | 成果物の最小収録集合の宣言（V-10） | FW laneのESP-IDF buildツリーのように再生成可能で大きい出力を区別し、lane summaryへ「収録すべき最小成果物集合」を機械可読に宣言する。成果物の必須性判定（U-5）は変更しない |

15.1〜15.13は達成済みで実装記録は[`roadmap-completed.md`](roadmap-completed.md)にある。15.14〜15.19は未着手であり、15.17〜15.19は第6回実機実測と成果物回収（V-4、V-8、V-10）を出所とし、例示・計測・収録の手順側だけを整備する項目であり、判定と閾値には触れない。

## マイルストーン16: 設計能力の拡張

設計拡張候補Aを、設計契約と決定論的ゲートの拡張として扱う。設計述語とgraph拡張は
マイルストーン14.2の契約registryを前提とする。

16.5で残留する単一故障点は、除去せずに受容する場合もクリティカル項目として根拠付きで列挙し、検査対象外にした箇所はその理由を記録する。列挙のない状態を「単一故障点なし」と解釈しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 16.1 | 4層基板・階層graph対応 | 現行の2層・フラット構造前提を拡張し、stackup宣言、差動ペア・インピーダンス管理配線の契約とゲートを追加する |
| 16.2 | バッテリ駆動製品対応 | 充電IC・残量計・保護回路の設計述語と、電力バジェット（消費電流と容量の収支）を宣言由来の入力から決定論的に検査するゲートを追加する |
| 16.3 | EMC/ESD設計述語 | 外部コネクタへの保護素子の有無、電源ループ面積、リターンパス連続性のチェックを設計述語として追加する（認証適合の判定はしない） |
| 16.4 | テスト容易化設計（DFT） | テストポイントのネットカバレッジをゲート化し、プローブアクセス（最小間隔・径）を検査する |
| 16.5 | 構造安全性述語 | 冗長経路が同一コネクタ・同一ハーネス・同一電源バス・同一IC・同一via・同一熱経路・同一保護素子を共有していないかの単一故障点／共通原因検査、電源ツリー全体での保護の選択性（下流が上流より先に切れるか、短絡の封じ込め範囲、保護素子と被保護機能が同一ICへ集約されていないか）、ネットの信号クラス宣言と非互換な同一コネクタ・隣接配置の検出、クリティカル回路に限定したスニーク解析（意図しない導通経路・タイミング・表示・表記）、導体の台形断面を考慮した許容電流評価を設計述語として追加する。適用条件と有効域は14.2の契約registryで宣言し、宣言のない範囲はunknownとして停止側へ集約する（認証適合の判定はしない） |

16.1〜16.5は計画である。

## マイルストーン17: 部品・サプライチェーン統治

部品・BOM関連の拡張候補Bと統治項目を扱う。部品属性を設計契約へ接続する範囲は
マイルストーン14.2の契約registryを前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 17.1 | 部品ライブラリ統治SKILL | footprintのpad寸法・courtyard・原点をライブラリ契約として検査する。`examples/sensor-node-20260820/`のreportで観測されたDRC警告30件（`lib_footprint_issues`）の類型に対応する |
| 17.2 | EOL・セカンドソース管理契約 | 部品のライフサイクル状態と代替候補を宣言contractとして記録し、未宣言はunknownとして停止側へ集約する（外部APIの自動照会は別途判断） |
| 17.3 | BOMコンプライアンス事前チェック | BOM部品属性からRoHS等の申告状況を集計し、不明部品をunknownとして列挙する（適合判定はしない） |
| 17.4 | BOMコスト・代替部品検討 | JLCPCB basic/extended区分や代替候補の整理を、保存済み見積入力（7.1契約）の範囲で支援する |

17.1〜17.4は計画である。

## マイルストーン18: 量産・出荷準備lane

量産準備、組立性、出荷検査の経路を整備する。graphから検査項目を導出する範囲は
マイルストーン14.2の契約registryを前提とし、18.1はマイルストーン5の実機フィードバックへ接続する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 18.1 | ブリングアップ試験計画の生成 | 実機フィードバック（マイルストーン5）の入力となる測定点・期待値・手順のチェックリストをgraphから生成する |
| 18.2 | 面付け（panelization）対応 | 小基板の面付けガーバ生成とDFM再検査を追加する |
| 18.3 | 製造しやすさ（DFA）レビューSKILL | 組立性・作業性・生産性の観点（部品の向きの統一、片面実装可否、手はんだ部品のアクセス性、コネクタ・ケーブルの組付け順序、筐体組立の工数、治具の要否）をレビュー観点として構造化し、graph・配置・筐体形状からL2所見として報告する |
| 18.4 | 出荷検査文書生成SKILL | 出荷検査の検査項目・実施方法・合否判定基準（外観、導通・電源電圧、書き込み・起動確認、LED・センサ動作、期待シリアル出力）を生成する。判定基準の値はgraph・ゲート閾値・FW投影由来に限定し、出所のない基準を作らない。導出できない項目はunknownとして人手決定欄を残す。生成文書はマイルストーン9のprovenance規則に従い`out/docs/`へ格納する |
| 18.5 | 出荷検査モード付きFW開発機能 | 出荷検査文書と対になる検査モード（自己診断・検査シーケンス）をFWへ組み込む開発機能を追加する。検査モードはUART等の明示操作でのみ起動し、検査項目（LED点灯、I2Cセンサ応答、電源電圧の自己確認等）と結果出力形式を出荷検査文書生成SKILLと同じ知識源（graph・FW投影）から導出する。検査結果の出力はprovisional観測であり、実測Evidenceへの昇格はマイルストーン5の実機フィードバック契約に従う |

18.1〜18.5は計画である。

## マイルストーン19: FWセキュリティと検証拡張

FWセキュリティと検証の拡張候補Cを扱う。FW契約と検証項目の追加は
マイルストーン14.2の契約registryを前提とし、19.2はマイルストーン5の実機HIL測定Evidenceへ接続する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 19.1 | secure boot・flash暗号化・OTA設計対応 | パーティション構成・鍵管理境界・OTAスロットを宣言として扱い、ビルド設定との整合をゲート化する。鍵素材は扱わない |
| 19.2 | QEMUコードカバレッジと実機HIL接続 | QEMU実行でのカバレッジ計測を追加し、実機フィードバック（マイルストーン5）のHIL測定Evidenceへ接続する |

19.1〜19.2は計画である。

## マイルストーン20: 改訂管理とレビュー運用

改訂・レビューに関する拡張候補D・Eと運用項目を扱う。20.1はマイルストーン13.6の
ECO記録と対応し、20.4はマイルストーン8.4のvision経路を前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 20.1 | ECOワークフローとrevisionライフサイクル | 設計変更指示（変更理由・影響範囲・再検証要件）をcontract化し、revision遷移とゲート再実行の対応関係を文書化する。マイルストーン13.6と対応付ける。ECOのclose条件には13.1の水平展開列挙の消化状況を含め、未消化の対象が残るrevisionをclose扱いにしない |
| 20.2 | graph差分投影 | revision間のgraph差分（追加・削除・属性変更）を視覚投影し、レビュー資料へ統合する |
| 20.3 | GitHub Actions統合 | 設計変更PRへゲート結果・Evidence要約を自動コメントする。コメントはL3提示であり合否権限を持たない |
| 20.4 | 視覚投影の自動品質検査 | 8.4のvision経路で投影の可読性（文字の重なり、極小表示、コントラスト）をL2所見として検出する。`examples/sensor-node-20260820/`のreportで観測されたfont-size問題の再発防止に対応する |
| 20.5 | トークン・コスト予算ガード | セッションのトークン消費・実行時間をL2で監視し、予算超過を警告する（実行の強制停止はhook側の判断とする） |

20.1〜20.5は計画である。

## マイルストーン21: 構想ブラッシュアップと分野横断の責務割当

会話で持ち込まれた「ものづくりアイデア」を設計入力へ落とせる水準まで洗練し、洗練後の
機能群を機構・機械・電気・FW・PC側ソフト・サーバ・スマホアプリのどこへ配置するかを
決める上流段階を扱う。要件レコード化とgraph差分への反映はマイルストーン14.5、
生成文書のprovenance規則はマイルストーン9、出所引用はマイルストーン12の索引contractを
前提とする。PC側ソフト・サーバ・スマホアプリ自体の開発は将来構想のままであり、
本マイルストーンは配置先の宣言と検査までを範囲とする。

アイデアのブラッシュアップは一回の生成でなく、OpenHandsの会話上で利用者と往復しながら
進める反復経路として扱う。agentは未決論点を優先度順に少数ずつ問い、利用者の回答と
選択をアイデアrecordへ追記し、残ったunknownを持ち越す。利用者が回答していない項目を
agentが推測で埋めない。

設計原則は次のとおりとし、既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩めない。

- アイデアの洗練とレビューはL2操舵・L3観測であり、合否権限を持たない。SKILLの所見だけで
  アイデアを要件へ昇格させず、確定した内容だけを宣言contractへ記録する。
- 対話の各ターンでは利用者が同意した事項と未決論点を区別して記録し、同意のない提案を
  確定として扱わない。対話の途中状態は保存し、中断・再開で同じ未決論点から続けられる。
- 対話ログは内部向けの知識源にとどめ、公開文書へは含めない（マイルストーン12.4と同じ規則）。
- ブラッシュアップの指摘・代替案は、知識源（設計graph、rationale、ゲート閾値、Evidence、
  過去の設計例、部品・fab profile）を出所として提示する。出所のない断定を出さず、
  導出できない論点はunknownとして残し、人手決定欄を設ける。
- 責務割当の判断は設計入力・制約・rationaleを出所とする決定論的な検討として扱う。
  割当結果はDesign Graph等の設計入力contractへ宣言として記録し、投影を設計入力へ
  逆流させない不変条件を維持する。
- 未割当、根拠のない多重割当、配置先の能力宣言と矛盾する割当、導出不能はfail-closedで
  停止し、「問題なし」とは解釈しない。
- コスト・消費電力・体験の比較値を推定する場合は推定であることを明示し、authoritative
  Evidenceへ昇格しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 21.1 | アイデアrecord契約 | 目的、想定ユーザ、実現したい体験、想定使用環境、既知の制約（コスト、寸法、電源、通信、法規）、成功条件をアイデアrecordの宣言contractとして定義する。各項目は`confirmed`（利用者が同意済み）と`open`（未決）を区別し、未宣言項目はunknownとして記録して要件確定へ進めない |
| 21.2 | 対話型ブラッシュアップSKILL | 利用者との往復でアイデアを洗練するSKILL（例: `/acd:ideate`）を追加する。一回の応答で結論を出さず、未決論点の優先度順に質問を少数ずつ提示し、各質問には選択肢とトレードオフ、推奨案とその出所を添える。利用者の回答を`confirmed`としてrecordへ追記し、未回答は`open`のまま残す。SKILLはL2操舵であり、推測でrecordを埋めない |
| 21.3 | 対話状態の保存と進捗提示 | ターンごとの質問・回答・決定を追記履歴として保存し、中断した対話を同じ未決論点から再開できるようにする。`confirmed`件数と残り`open`件数、確定を妨げているunknownを毎ターン提示する。提示はL3観測であり進捗率を合格根拠にしない |
| 21.4 | 実現可能性の粗見積 | アイデアrecordから必要機能・主要部品・概算コスト・概算消費電力・想定寸法を粗見積として算出し、成功条件との矛盾を停止側の論点として報告する。見積は推定であり合格根拠にしない |
| 21.5 | アイデアから要件への確定 | 洗練済みアイデアrecordを、マイルストーン14.5の要件レコードへ確定変換する経路を定義する。確定時はrationale recordを必須とし、unknownを残したまま確定できないようにする |
| 21.6 | 責務割当contract | 各機能の配置先候補（機構、機械、電気、FW、PC側ソフト、サーバ、スマホアプリ）と選定基準（応答時間、消費電力、コスト、更新頻度、安全性、通信可用性、保守性）を宣言contractとして定義し、選定根拠をrationale必須属性として分類する。候補の提示と選択は21.2の対話で行い、利用者が合意した割当だけをcontractへ記録する |
| 21.7 | 責務割当ゲート | 21.6の宣言に対し、全機能が配置先を持つこと、配置先の能力宣言（GPIO、通信手段、メモリ、電源、可動要件）と矛盾しないこと、分野境界のinterface（信号、プロトコル、電源）が両側から宣言されていることを決定論的に検査する。未割当・矛盾・unknownは停止させる |
| 21.8 | 構想と割当の投影・文書統合 | アイデアrecord、粗見積、責務割当表、分野横断のブロック図を再現可能な投影として`out/docs/`へ生成し、マイルストーン9の文書laneとマイルストーン8の視覚投影provenance規則へ統合する。投影は提示であり合否権限を持たない |

21.1〜21.8は計画である。採用する場合は、アイデアrecordと責務割当のcontract境界、
対話履歴の保存境界と公開除外規則、各分野のinterface宣言の範囲、責務割当のEvidence境界を
新規ADRで定義し、未定義の項目はunknownとしてfail-closedにする。

## 契約とマイルストーンの対応

契約はPydanticモデルを正本とし（フェーズ横断の検証要件6）、`src/acd/schema/`の
各モジュールは次のマイルストーンで定義した。`__init__.py`は再exportだけを行う。
表に対応先を持たない契約モジュールを追加しない。

| モジュール | 役割 | マイルストーン |
|---|---|---|
| `common.py` | 契約共通の値型 | 1 |
| `design_graph.py` | Design Graph正本 | 1 |
| `rationale.py` | 設計根拠record（`ADR-0021`） | 1・14.5 |
| `evidence.py` | Evidence record と`measured`／`virtual`分類 | 1・5.1・6 |
| `tool_envelope.py` | 外部ツール実行envelope（`exit_code`意味論は15.1） | 1・2・15.1 |
| `fab_profile.py` | 宣言的fab profileとprofile registry | 2・14.2 |
| `functional_block.py` | 機能ブロック述語の適用条件（`ADR-0043`） | 14.2 |
| `visual_projection.py` | 視覚投影の再現可能な観測 | 8.1・8.2・8.3 |
| `visual_crosscheck.py` | 機械可読投影との電気視覚照合（L3観測） | 8.5・20.4 |
| `quote.py` | 期限付き見積入力 | 7.1 |
| `order_scope.py` | 宣言された発注範囲 | 7.1 |
| `order_total.py` | 決定論的な総発注額 | 7.2 |
| `order_policy.py` | 発注policyと発注前最終ゲート結果 | 7.3・14.6 |
| `side_effect_journal.py` | append-onlyのside-effect journal | 7.4 |
| `order_execution.py` | 自働発注のdry-run出力 | 7.5 |
| `receipt.py` | 製造・組立受領の取り込み | 5.2 |
| `functional_run.py` | FW書き込みと機能測定 | 5.3 |
| `feedback.py` | 測定結果からのproposal（入力へ逆流させない） | 5.4 |
| `agent_settings.py` | secret-freeなsettings・profile・credential | 4.4 |
| `context.py` | context memoryとevent viewの非authoritative観測 | 4.4 |
| `prompt_manifest.py` | 役割promptの決定論的manifest | 4.4 |
| `model_routing.py` | 役割別modelルーティングpolicy | 4.4 |
| `observation.py` | 非authoritativeな観測payload | 4.4 |
| `observation_log.py` | secret-freeな構造化観測ログ | 4.4 |
| `knowledge_index.py` | 設計知識indexの契約 | 12.1 |
| `knowledge_answer.py` | 出典付きQA回答（`pass_evidence=false`） | 12.2 |
| `troubleshooting.py` | 症状から確認手順への機械可読知識 | 12.3 |
| `rejection_summary.py` | hook遮断理由の要約（L3観測） | 4.1・15.6 |
| `tool_registration.py` | SDK ToolDefinition登録面の契約 | 4・15.7 |

## ADRとマイルストーンの対応

Accepted ADRの索引は[`README.md`](README.md)を正とし、Superseded ADRは統合先を示す
pointerだけを残す。本書はSuperseded ADRを現行決定として引用しない
（`ADR-0025`は`ADR-0026`により対象外化された履歴として現在地でのみ参照する）。

| ADR | 決定 | マイルストーン |
|---|---|---|
| [`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md) | JLCPCB PCBA発注準備の契約と宣言データ | 7.1・7.3・15.2 |
| [`ADR-0006`](adr/ADR-0006-vendor-submodule-policy.md) | SDK vendor submoduleの更新方針 | 4・14.8 |
| [`ADR-0007`](adr/ADR-0007-llm-guided-physical-design.md) | 配置・回転・配線探索へのLLM適用境界 | 4.3・14.4 |
| [`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md) | VibeBBの最小構成とSDK優先の実装境界 | 1・4・14 |
| [`ADR-0021`](adr/ADR-0021-design-rationale-records.md) | 設計根拠recordの保持 | 1・14.5・21.5 |
| [`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md) | 判定・操舵・観測の三層分離 | 全マイルストーン（フェーズ横断の検証要件） |
| [`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md) | OpenHands委譲契約 | 4・4.1〜4.4・6・agent-server採用判断 |
| [`ADR-0027`](adr/ADR-0027-single-distribution.md) | 単一配布パッケージ | 4・14.9 |
| [`ADR-0028`](adr/ADR-0028-execution-provenance.md) | 実行provenanceとauthoritative Evidence | 6・7.3・検証要件 |
| [`ADR-0033`](adr/ADR-0033-sdk-capability-adoption.md) | SDK能力の採否とbrowser_useの境界 | 4.4・4.5 |
| [`ADR-0034`](adr/ADR-0034-document-governance.md) | 文書統治とSDK能力カタログ | 4.5・9 |
| [`ADR-0035`](adr/ADR-0035-standard-distribution.md) | SDK標準機構による配布とインストール | 4・14.9 |
| [`ADR-0036`](adr/ADR-0036-ambient-plugin-install.md) | installed plugin自動読み込みによるインストール | 4・14.8 |
| [`ADR-0037`](adr/ADR-0037-pep723-skill-scripts.md) | PEP 723によるSkill scriptの依存自己解決 | 14.1 |
| [`ADR-0038`](adr/ADR-0038-acd-install-doctor.md) | ACDインストール自己診断入口 | 14.1・14.8・15.7・15.8 |
| [`ADR-0039`](adr/ADR-0039-subagent-skill-reference.md) | sub-agentのSkill参照方式 | 4・4.3 |
| [`ADR-0040`](adr/ADR-0040-hook-plugin-root-resolution.md) | plugin hookのplugin root解決方式 | 4.1 |
| [`ADR-0041`](adr/ADR-0041-vision-proposals-as-design-candidates.md) | ビジョン出力を宣言層入力として受け入れる境界 | 8.4・8.6・20.4 |
| [`ADR-0042`](adr/ADR-0042-skill-package-ref-skew.md) | Skill package refのskew検出と事前導入 | 14.1 |
| [`ADR-0043`](adr/ADR-0043-functional-block-contract-registry.md) | 機能ブロック契約registryによる設計述語の適用条件 | 14.2・16 |

## Skill・command・scriptとマイルストーンの対応

plugin資材とscriptの成果物対応を示す。SkillとcommandはL2操舵・L3観測であり、
表の対応はマイルストーンの成果物としての帰属を示すものであって合否権限を与えない。

| Skill | マイルストーン |
|---|---|
| `acd-contracts` | 1・4 |
| `acd-design-rationale` | 1 |
| `acd-silkscreen-placement` | 2 |
| `acd-cad-determinism-probe` | 3 |
| `acd-placement-search` | 4.3・14.4 |
| `acd-firmware-esp32c3` | 5.3・8.5・15.9 |
| `acd-install-doctor` | 14.1・14.8・15.7・15.8 |
| `acd-product-docs` | 9.1・9.2 |
| `acd-theme-song` | 9.6 |
| `acd-design-knowledge` | 12.1〜12.5 |
| `acd-qc-seven-tools` | 9.3・9.4のL2前段（所見の整理） |
| `acd-reliability-review` | 7.3・9.4のL2前段（余裕のレビュー） |
| `acd-package-contract.json`／`acd-package-ref.txt` | 14.1 |

| command | マイルストーン |
|---|---|
| `/acd:gates` | 4・4.1 |
| `/acd:ask` | 12.2 |
| `/acd:doctor` | 14.1・14.8・15.7・15.8 |

| script | マイルストーン |
|---|---|
| `verify_all.py` | 検証要件（段階の正）・14.7（E-6） |
| `verify_docs.py` | 検証要件・4.1 |
| `verify_sdk_capabilities.py` | 4.5 |
| `verify_agent_prompts.py` | 4.4 |
| `verify_model_policy.py` | 4.4 |
| `verify_agent_settings.py` | 4.4 |
| `verify_context_view.py` | 4.4 |
| `verify_acd_tool_registration.py` | 4・15.7 |
| `verify_authoritative_evidence.py` | 6 |
| `verify_skill_metadata.py` | 14.1 |
| `verify_skill_package_ref.py` | 14.1 |
| `update_skill_package_ref.py` | 14.1 |
| `probe_pinned_acd_graph.py` | 14.1 |
| `probe_tools.py` | 4.1 |
| `print_locked_image.py` | 6 |
| `run_in_workspace.py` | 6 |
| `resolve_gd1_silkscreen.py` | 2 |
| `silkscreen_search.py` | 2 |
| `run_gd1_pipeline.py` | 2 |
| `run_design_lanes.py` | 2・3 |
| `run_enclosure_pipeline.py` | 3 |
| `build_gd1_fixture.py` | 14.5 |
| `check_rationale.py` | 1 |
| `fetch_lcsc_footprint_orientation.py` | 7.1・17.1 |
| `ingest_receipt.py` | 5.2 |
| `ingest_functional_run.py` | 5.3 |
| `propose_input_feedback.py` | 5.4 |
| `pre_order_gate.py` | 7.3 |
| `order_execution.py` | 7.5 |
| `side_effect_journal.py` | 7.4 |

## 検証要件

変更ごとに、契約・投影・独立再読込・決定論的ゲートを実行する。ツール不在、
parse失敗、未実行、unknownはfail-closedとする。検証段階の正は
`uv run python scripts/verify_all.py --stage docs`、`--stage standard`、`--stage full`
であり、Markdownのみの変更も該当する段階コマンドで検証する。

## フェーズ横断の検証要件

以下は全マイルストーンの完了条件に共通して要求する。固有の達成条件が満たされても、
ここに反する実装は合格にしない。これらは実際の欠陥類型に基づく設計判断であり、
外部リポジトリの記述を権威として引くものではない。

| # | 要件 | 禁止する構造 |
|---|---|---|
| 1 | 判定の両辺は別の出自から取る | 自分が生成した成果物の存在を自分の合格根拠にする（自己証明）。replay結果同士、生成器同士の比較 |
| 2 | 導出できない入力は`unknown`として停止側へ集約する | `continue`・早期return・既定値補完でskipを合格に見せる。宣言の欠如を0や空と同一視する |
| 3 | 実行中のstageを入場時に宣言し、失敗はその宣言から帰属させる | 直前の成功結果や末尾要素を失敗の帰属先にする |
| 4 | CIが読み込む入力・fixture・scriptはtrackedにし、typecheck／lintの対象に含める | 検査対象外の領域を「検査済み」と扱う。gitignore下のデータに依存する回帰 |
| 5 | 外部ツールの保存バイト列を設計状態の権威にしない。非決定な出力は正規化規則を契約に書き、規則外の差異は停止条件とする | 外部ツールの決定論性を説明で仮定する（timestamp、再保存時のセグメント構成差など） |
| 6 | 契約はPydanticモデルから導く | runnerと文書でgate番号・状態を二重管理する |
| 7 | 安全条件・保護対象は書き換わる部分木で判断する | pathの完全一致だけで許可・却下を決める |
| 8 | 予算（token、money、wall-clock、外部process回数）を各ゴールデンタスクで実測して記録する。`ADR-0026`の観測境界に従いSDK `Metrics`／`ConversationStats`と外部ツールの実行記録を使う | 予算を実測せず見積や説明で代替する。`Metrics`／`ConversationStats`出力を合格根拠へ昇格させる |
| 9 | 探索を含む工程では、代理指標スコアを合格根拠にせず、停止理由と実行結果を記録する | 代理指標をL1合否へ混入する。停止理由を記録しない |

## 見直し条件

外部ツールの非決定性が正規化できない、一次情報とライセンス境界が合わない、
negative testなしでしか完了条件を満たせない場合は、その機能を止めてADRと本書を
更新する。閾値・期待値を変更して成功に見せない。
