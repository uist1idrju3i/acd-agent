# ACD向け先行事例台帳

> ステータス: Draft  
> 対象: 公開先行事例、調査日 2026-08-11 UTC
> 2026-08-13に、部品ライブラリとライブラリ品質検査（§3.1）、製造ベンダークライアントとEDA→fab送信経路（§8.1）の追加調査を追記。

本書は、将来の高信頼化のための調査記録であり、現在の規範ではありません。
公開先行事例、一次情報の確度、ライセンス境界、ACDとの差分候補を扱う調査台帳を
正とする。製品の設計原則は [`../README.md`](../README.md)、実装方針は
[`architecture.md`](architecture.md)と [`roadmap.md`](roadmap.md)を参照する。

## 0. 調査方法と読み方

別リポジトリ `uist1idrju3i/ACD` のREADMEに列挙されたツール一覧を出発点とし、
各対象を一次情報から再調査した。参照元の方向性や「ACDへの教訓」欄は、
本台帳の設計判断には引き継いでいない。

### 0.1 このレポートの確度

今回の追加調査では、対象リポジトリのLICENSE本文を取得できたもの、公式
GitHub Releases APIまたは公式releaseページで版番号・公開日を取得できたものを
「一次情報で確認済み」とした。README、検索結果、パッケージメタデータだけを
根拠にしたものは「二次情報のみ」とし、取得不能・同定不能なものは「未確認」
とした。件数は対象の重複（例: KiCad本体と`kicad-cli`）を一件として数えた。

- **一次情報で確認済み:** 約24件（LICENSE本文、または公式release情報の少なくとも一方を取得）
- **二次情報のみ:** 約14件（README・公式説明は確認したが、LICENSE本文または版番号の一次確認が不足）
- **未確認:** 約4件（対象URLのLICENSE/releaseが404、API拒否、または対象を一意に同定できず）

上記の件数は、2026-08-13の§3.1部品ライブラリ調査分と§8.1製造ベンダークライアント調査分を含まない。

この分類は「法的に利用可能」と同義ではない。依存ライブラリ、同梱データ、
プラグイン、商標、特許、商用API契約は別途確認が必要である。

対象の固有名詞とURLは別リポジトリのREADMEから抽出し、一次情報は公式サイト、
公式ドキュメント、公式GitHub、arXivを優先した。GitHubの最新release/dateや
ライセンスは、調査時に取得できた公式情報を根拠にした。取得できなかった項目は
「確認できず」と書いた。

「決定論的」は、同一バージョン・入力・環境でCLI/APIを再実行する設計が
可能、という意味であり、計算結果の完全なbit-for-bit再現を本調査で保証した
という意味ではない。商用サービスの価格、契約、API権限、最新versionは
アカウントや地域で変わるため、公開ページで確認できないものを推測しない。

## 1. コード駆動・言語系

| 名称／一次URL | 種別・ライセンス | 機能の実体 | 自動化境界／入出力 | 最新状況（2026-08-11確認） | acd-agent関連度・役割 | 不確実性 |
|---|---|---|---|---|---|---|
| [diodeinc/pcb (Zener)](https://github.com/diodeinc/pcb) | OSS。リポジトリLICENSEのSPDXは本調査で未取得（不明） | Starlark系Zenerで回路を記述し、`pcb` CLIが依存管理とKiCadレイアウト生成を行う。 | CLI。Zenerソース→KiCad schematic/PCB等。ヘッドレス可能。固定toolchainなら決定的に呼べる設計。 | READMEの最新release/version/dateは確認できず。GitHubページは2025-01-24公開情報を返した。 | **高**。意図記述→KiCad投影の参照実装。 | exact release、全出力、licenseは確認できず。 |
| [tscircuit](https://github.com/tscircuit/tscircuit) | OSS。SPDXは未確認（不明） | TypeScript/Reactで回路を記述し、Circuit JSONへ変換。ブラウザでschematic/PCB/3Dを表示し、Gerber、BOM、pick-and-placeを出力。registry/package managerとautoutingも提供。 | TypeScript API、CLI `tsci`、ブラウザ。入力TS/TSX・Circuit JSON→Gerber/BOM/PnP。renderはGUI/ブラウザ依存、exportはヘッドレス可能な範囲あり。 | 公式GitHub READMEで機能を確認。release/dateは本調査では取得できず。 | **高**。正規JSONと投影の比較対象、部品単位patchの設計候補。 | autorouterの保証、完全なCLI再現性は確認できず。 |
| [atopile](https://github.com/atopile/atopile) | OSS。SPDXは未確認（不明） | `.ato`宣言言語。units、tolerances、interfaces、assertions、parametric component selection、KiCad layout、BOM/fab/assembly/reportを扱う。 | `ato`/VS Code/Cursor。buildはCLI/CIでヘッドレス可能、KiCad GUIは閲覧・編集時のみ必要。`.ato`→KiCad files、BOM、manufacturing data。 | READMEの機能と公式docsへの導線を確認。release/dateは未確認。 | **高**。要求・制約・許容差を実行可能表現にする比較対象。 | license、solverの決定性、MCAD対応は未確認。 |
| [JITX](https://www.jitx.com/) | 商用。ライセンス／価格は公開範囲で不明 | Stanza言語によるcode-driven PCB design、制約、simulation-in-the-loop、製造向け設計。 | 言語/コンパイラと商用環境。出力形式、headless/API詳細は公開ページだけでは確認できず。 | 現行version/dateは公開ページで確認できず。 | **中**。商用code-CADの比較対象、制約コンパイルの参照。 | 詳細API・license・輸出機能は契約確認が必要。 |
| [SKiDL](https://github.com/devbisme/skidl) | OSS。READMEはPython package、SPDXは本調査で未確認（不明） | Python programで回路を記述し、KiCad等のPCB tool向けnetlistを生成。部品ライブラリ・ERC系を扱う。 | Python API/CLI相当。Python→netlist。KiCadが主対象だがtool-independent拡張を掲げる。ヘッドレス可能。 | GitHub READMEの説明を確認。最新release/dateは未確認。 | **高**。回路グラフとnetlist投影の参照。 | 配置・配線、MCAD、現行versionは確認できず。 |
| PHDL | 言語／研究・OSS状況不明。license不明 | README §6ではテキスト記述言語として列挙されている。具体的な公式一次URL・現行実装を特定できず。 | 実行境界・入出力とも確認できず。 | 確認できず。 | **低**。調査対象名として記録。 | 同名プロジェクトを一意に同定できず。 |

## 2. 商用・AI ECAD／部品・要件

| 名称／一次URL | 種別・license | 機能 | 自動化境界／形式 | 最新状況 | 関連度・役割 | 未確認 |
|---|---|---|---|---|---|---|
| [Flux.ai](https://www.flux.ai/p)、[Steerable Hardware Agent](https://www.flux.ai/p/blog/new-steerable-hardware-agent) | 商用、 proprietary | Browser ECAD、AI copilot/agent。公式発表はsteerable agentと実行中の設計方向修正を説明。 | Web GUI中心。公開REST/MCP/CLI、headless exportの全範囲は確認できず。設計・DRC/検証はサービス内。 | 2026発表記事を確認。製品version/価格は未確認。 | **高**。要求対話と途中steeringの比較対象。 | API契約、データexport、決定性、ライセンス不明。 |
| [Quilter](https://www.quilter.ai/) | 商用、proprietary | 物理制約駆動PCB auto-layout、BGA fanout等を掲げる。 | Web/serviceまたは連携APIの詳細は公開範囲で確認できず。入力・出力形式も要契約。 | 2026のBGA/impedance等の発表はREADME列挙で、公式ページの現行versionは未確認。 | **高**。候補生成＋物理制約スコアの比較。 | via種類・API・再現性・価格不明。 |
| [CELUS](https://www.celus.io/) | 商用、proprietary | 要件からfunctional block、回路、部品選定を支援するAI platform。 | Web GUI中心。公開headless/API詳細は未確認。出力形式は製品契約依存。 | 現行version/date未確認。 | **高**。要求→回路アーキテクチャ工程の比較。 | layout範囲、API、license不明。 |
| [SnapMagic/SnapEDA](https://www.snapmagic.com/)、[SnapMagic Design](https://design.snapmagic.com/) | 商用サービス。proprietary | SnapEDAはsymbol/footprint/3D model library。SnapMagic Designはprompt→schematic、real components、design checksを掲げる。 | Web/APIの公開範囲は部品検索中心。CAD library形式は各EDA向け、サービス自動化範囲は要確認。 | 製品version/dateは確認できず。 | **高**。部品・footprint evidence source。 | prompt製品のAPI、ライセンス条件、最新status不明。 |
| [Ultra Librarian](https://www.ultralibrarian.com/) | 商用／library service、proprietary | ECAD symbol/footprint/3D library、CAD format download。 | Web download/API契約の詳細は未確認。出力はEDA library formats/3D。 | 現行version/date不明。 | **高**。部品モデルの取得・provenance source。 | API、再配布権、全formats不明。 |
| [EasyEDA](https://easyeda.com/)、EasyEDA Pro API | 商用/browser ECAD、proprietary | Browser schematic/PCB、LCSC/JLCPCB連携。EasyEDA Pro APIの公開範囲は注文・manufacturing dataのbeta説明がある。 | GUI/Web。APIが常時公開か、注文をheadless実行できるかは確認できず。JSON/Gerber/BOM等は製品依存。 | APIの現行version/dateは確認できず。 | **高**。ECAD→fabの比較対象。 | API access、automated purchase可否、vendor lock-in条件不明。 |
| [Circuit Mind](https://www.circuitmind.io/) | 商用、proprietary | Requirements/architectureからschematic、BOM、verificationを扱うACE。 | Web/service。公開ページではPCB layout API/CLIは確認できず。schematic/BOM等。 | version/date不明。 | **高**。要求→アーキテクチャとpart selectionの比較。 | simulation/実機、API、価格不明。 |
| [Cofactr](https://www.cofactr.com/) | 商用、proprietary | hardware lifecycle・sourcing・BOM・supply chain platform。 | SaaS/APIの詳細は契約依存。BOM/part/supply data。 | version/date不明。 | **中〜高**。部品出所、在庫、調達Evidence source。 | design synthesisと公開APIは未確認。 |
| [Cadence Allegro X AI](https://www.cadence.com/en_US/home/tools/pcb-design-and-analysis/pcb-design/allegro-x-ai.html) | 商用、proprietary | Allegro PCB designにAIによる配置・配線等を統合する製品。 | GUI/商用EDA。headless automationとAPIは公開範囲で不明。Cadence native formats。 | 現行version/date不明。 | **中〜高**。商用physical design比較。 | AI agent API、再現性、価格不明。 |
| [Cadence Cerebrus](https://www.cadence.com/en_US/home/products/digital-design-and-signoff/ai-driven-digital-design/cerebrus-intelligent-chip-explorer.html) | 商用、proprietary | RTL-to-signoffのdigital/ASIC design space exploration、AI最適化。 | EDA flow integration、batch可能性は製品契約依存。RTL/constraints/reports。 | version/date不明。 | **中**。多目的探索・候補比較のASIC類例。 | PCB/MCADではなく、ACD直接代替ではない。 |
| [Synopsys DSO.ai](https://www.synopsys.com/ai/ai-powered-eda.html) | 商用、proprietary | Digital design space optimization、PPA/signoff探索。 | 商用EDA flow/batch。形式はSynopsys flow。 | version/date不明。 | **中**。候補探索とevidenceの類例。 | PCB/MCAD、API、価格不明。 |
| [Altium 365](https://www.altium.com/altium-365) | 商用クラウド、proprietary | ECAD workspace、design data、collaboration、AI機能。 | Web/desktop integration、APIは別developer programの範囲。Altium files/PCB/BOM等。 | 現行version/date不明。 | **高**。設計データ管理・collaboration比較。 | AI機能のheadless境界不明。 |
| [Agentic Requirements Engineering](https://resources.altium.com/p/introducing-agentic-requirements-engineering) | 商用feature、proprietary | Altium Requirements Portalのagentic requirements作成・変更・レビュー。 | Web portal、常駐agentは記事上coming soon。要求データ形式/API不明。 | 2026-07-28発表としてREADMEに列挙。現行提供状況は確認できず。 | **高**。要求を正規artifactにする比較。 | GA status、API、license不明。 |

## 3. OSS EDA基盤・配線

| 名称／URL | 種別・SPDX | 機能・境界 | 入出力／最新 | 関連度・未確認 |
|---|---|---|---|---|
| [KiCad](https://www.kicad.org/)、[source](https://gitlab.com/kicad/code/kicad) | OSS。各component licenseが混在するため、配布時は公式LICENSEを確認。 | Schematic/PCB/3D、ERC/DRC、libraries、export。`kicad-cli`はschematic/PCB/symbol/footprintの自動処理を提供。 | 公式KiCad 10.0.0 releaseは2026-03-20。10.0 CLI docsはmanual 10.0.5ベースで、`fp/jobset/pcb/sch/sym/version`を列挙。`.kicad_sch/.kicad_pcb`→Gerber, drill, BOM, PDF, 3D等。 | **最高**。deterministic verifier/projection target。10.0.5の正確なrelease dateは本調査では確認できず。 |
| KiCad IPC API / [kicad-python](https://docs.kicad.org/kicad-python-main/kicad.html) | KiCad同梱OSS。SPDX詳細は未確認。 | KiCad running sessionへprotobuf/NNG経由でboard等をinspection/edit。kicad-pythonは公式binding。 | IPCはKiCad 10系で利用。GUI process必須の操作とCLI可能な操作が混在。 | **最高**。guarded live mutation。回路図APIの版別範囲は未確定。 |
| [KiCanvas](https://github.com/theacodes/kicanvas) | OSS。SPDX未確認。 | Browser schematic/PCB viewer/rendering。 | Browser/JS。KiCad files→canvas/image/interactive view。編集・headless DRCは確認できず。 | **中**。human review projection。version/date不明。 |
| [kiutils](https://github.com/mvnmgrx/kiutils) | OSS。SPDX未確認。 | KiCad S-expression filesをPythonでparse/write。 | Python API。`.kicad_sch/.kicad_pcb`等→Python objects→files、GUI不要。 | **高**。deterministic parser/patcher。version/date不明。 |
| [kicad-skip](https://github.com/psychogenic/kicad-skip) | OSS。SPDX未確認。 | KiCad fileをPython/S-expressionとして扱うライブラリ。 | Python API、headless。KiCad S-expression。 | **中**。投影・差分の比較。現行status不明。 |
| [freerouting](https://github.com/freerouting/freerouting) | OSS Java。SPDXは本調査で未確認。 | PCB autorouter。 | CLI/GUI/Java。KiCad等からDSNを入力しSESを出力する交換境界。headless CLI可能。 | **最高**。router worker。version/release date/license exactは未確認。 |

### 3.1 部品ライブラリとライブラリ品質検査（2026-08-13追加調査）

ライブラリ記述の誤りはERC/DRCだけでは検出できないため、部品ライブラリそのものの
出所・ライセンス・生成方法・検査手段を独立した調査対象として扱う。以下は本節の
追加調査で、リポジトリのLICENSE本文、GitLab/GitHub API、READMEを一次情報として
取得できた範囲を記録する。

| 名称／一次URL | 種別・license | 実体・生成方法 | 自動化境界／入出力 | 最新状況（2026-08-13確認） | acd-agent関連度・役割 | 不確実性 |
|---|---|---|---|---|---|---|
| [CERN KiCad Libraries](https://gitlab.com/ohwr/cern-kicad-libs) | OSS。`LICENSE`と`LICENSES/`、`.reuse/dep5`で`CERN-OHL-P-2.0`（permissive variant）を明示。dep5のcopyrightは`2024-2025 CERN`。 | CERNのElectronics Design Officeが保守するAltium Designer原本を、CERN GitLabのpipelineが`kicad-cli`で毎晩変換したsymbol/footprint。SchLib 29個の`.kicad_sym`、PcbLib 59個の`.pretty`。3D modelとdatasheetは第三者IPを含むため非同梱。 | Git clone。`CERN.sqlite`＋`CERN_Linux/Windows.kicad_dbl`のKiCad database libraryとして使う設計で、ODBC driverが必要。symbol/footprintを個別に登録する使い方は想定外とREADMEが明示。`sym-lib-table`/`fp-lib-table`を同梱。 | tag/releaseはなくmaster nightly。最新commitは2026-08-13T01:05Z、著者は`CERN KiCad Library Bot`で、commit messageにpipeline URL、job URL、source commitを記録。生成はKiCad 9.x系、10.x互換、10.xネイティブ版はREADME上「coming soon」。 | **高**。permissive licenseで再配布境界が明確な実部品ライブラリであり、(a)ライブラリ生成pipelineのprovenance記録、(b)`CHECKSUMS`（ライブラリファイル単位のMD5）、(c)database library形式という三点がACDの部品Evidence設計の参照になる。 | 変換ログ（`schlib_conversion_log.txt`等）は変換対象名の列挙であり、KiCad版・変換設定・入力hashまでは含まない。原本Altiumライブラリは非公開のため、変換の正しさを外部から再現検証できない。MD5は改竄検知用途には弱い。 |
| [KiCad公式ライブラリ](https://gitlab.com/kicad/libraries)（[kicad-symbols](https://gitlab.com/kicad/libraries/kicad-symbols)、kicad-footprints、[kicad-packages3D](https://gitlab.com/kicad/libraries/kicad-packages3D)） | OSS。`CC-BY-SA-4.0`＋設計向け例外（`Licensed Material`を使った設計とその生成物にarticle 3を放棄）。 | 公式symbol/footprint/3D model。KLC（KiCad Library Convention）に沿ってレビューされる。 | Git clone、KiCad同梱配布。`.kicad_sym`/`.pretty`/`.step`/`.wrl`。 | `kicad-symbols`の最新tagは`10.0.5`（2026-07-15）でKiCad本体版に追随。 | **最高**。既定の部品出所。例外条項により、設計成果物へのshare-alike波及は生じない読み方が公式見解。 | ライブラリ「集合」としての再配布・改変再配布はCC-BY-SA義務が残る。個々のsymbolの電気的正しさは保証されない。 |
| [kicad-library-utils](https://gitlab.com/kicad/libraries/kicad-library-utils) | OSS。`COPYING`は`GPL-3.0`。 | KLC準拠チェックのCLI群。`klc-check/check_symbol.py`、`check_footprint.py`、`check_3d_coverage.py`、`comparelibs.py`（同一ライブラリの2版比較、公式CIで使用）。 | Python CLI、headless。ライブラリファイル→違反レポート、版間diff。 | tagはなく、master更新（2026-08-11に活動）。独自ルール追加は現状forkが必要とREADMEが明記。 | **最高**。ライブラリ層の決定論的ゲート候補。symbol/footprint patchの前後で`comparelibs.py`によるdiffをEvidence化できる。 | GPL-3.0のためACD本体へのimport結合は避け、外部プロセス実行を前提にする。KLC適合はfootprint寸法がdatasheet通りである保証ではない。 |
| [kicad-footprint-generator](https://gitlab.com/kicad/libraries/kicad-footprint-generator) | OSS。READMEは`GPL-3.0-or-later`（ファイル単位の例外あり）。 | パラメータからfootprintと3D modelをscript生成する公式generator。 | Python script、headless。定義（yaml/script）→`.kicad_mod`/3D model。 | master更新。詳細手順は公式Wikiへ移設。 | **高**。手作業footprintではなく「生成物としてのfootprint」を扱う先行例で、生成器版＋入力定義をhash化すれば再現可能なライブラリ投影になる。 | GPL。生成物の再配布条件と、生成器の版差による出力変化は個別確認。 |
| [Digi-Key KiCad library](https://github.com/Digi-Key/digikey-kicad-library) | OSS。`LICENSE.md`はKiCad公式と同文の`CC-BY-SA-4.0`＋設計向け例外。 | Digi-Key品番に紐づくatomic parts（symbolにMPN・供給者情報を埋め込む方式）。 | Git clone。`digikey-symbols`/`digikey-footprints.pretty`。 | 最終pushは2024-03-16で、更新は停滞している。 | **中〜高**。symbolへ調達属性を持たせるatomic partsの参照例。ACDの部品provenance（MPN、lifecycle、price snapshot）を設計graph側に持つ方式との対比になる。 | 更新停止のため部品lifecycleの現況とは乖離しうる。release/tagなし。 |
| [Espressif KiCad Libraries](https://github.com/espressif/kicad-libraries) | OSS。`LICENSE.md`は`CC-BY-SA-4.0`＋設計向け例外（KiCad公式と同条件と明記）。 | ベンダー公式のSoC/module/DevKit symbol・footprint・3D model。v2.0.0以降はPCM（Plugin and Content Manager）配布、KLC準拠を掲げる。 | PCM addon、またはGit clone。KiCad 10向けと明記。 | 最新release `3.2.1`（2026-07-24）。 | **高**。ベンダー公式ライブラリをpinして使う運用の代表例。addon配布物はversionとhashを記録して固定できる。 | READMEは無保証を明記。footprint寸法のdatasheet照合Evidenceは別途必要。 |
| [SparkFun KiCad Libraries](https://github.com/sparkfun/SparkFun-KiCad-Libraries) | OSS想定だが**LICENSEファイルを確認できず**（GitHub license APIも404）。 | KiCad標準部品、SparkFun固有footprint、OSS 3D modelの混成。symbolに社内品番（`PROD_ID-*`）を持つ。 | PCM addonまたはGit clone。 | 最新release `v9.0.0`（2025-10-17）。 | **中**。社内品番をライブラリに埋める運用例。 | ライセンス未確認のため、ACDでの同梱・再配布は判断保留。 |
| [Horizon EDA pool](https://github.com/horizon-eda/horizon-pool) | OSS。`LICENSE.md`は`CC-BY-SA-4.0`＋設計向け例外。 | Horizon EDA本体のpool。unit／entity／symbol／package／part／padstackを別階層に分けたKiCadと異なるライブラリモデル。 | Horizon EDA固有format、pool管理CLI/GUI。 | 最終pushは2026-06-26。 | **中〜高**。「部品＝単一symbol＋footprint」ではなく、抽象unitから実部品までを型で分ける設計の参照。ACDの型付きライブラリモデルの比較対象。 | KiCadとの相互変換とheadless検査の範囲は未確認。 |
| [jlcparts](https://github.com/yaqwsx/jlcparts) | OSS、`MIT`（コードのライセンスであり、収集される部品データはJLCPCB/LCSC由来）。 | JLCPCB SMT assembly対応部品カタログをscrapeし、パラメトリック検索可能なDBとweb UIを生成。 | Python/JS、CI生成のDB＋静的サイト。releaseはなく、生成DBはgh-pages配布。 | 最終pushは2026-08-13。 | **高**。fab在庫と設計を突き合わせるためのデータ源。ACDでは「取得時点付きsnapshot」として扱えば部品選定Evidenceになる。 | 部品データ自体の再配布可否と正確性はJLCPCB/LCSC側の条件に従うため要確認。 |
| [kicad-jlcpcb-tools](https://github.com/Bouni/kicad-jlcpcb-tools) | OSS、`MIT`。 | KiCad plugin。LCSC品番の割当、部品DB検索、BOM/CPL生成。 | KiCad GUI plugin（PCM）。footprint fieldへLCSC番号を書き込む。 | 最終pushは2026-07-30。 | **中〜高**。fab固有属性を設計データへ書き戻す実装例。ACDでは属性の正はgraph側に置き、KiCadへは投影する設計と対比する。 | GUI plugin前提でheadless実行境界は未確認。 |
| [InvenTree](https://github.com/inventree/InvenTree) | OSS、`MIT`。 | 部品・在庫・BOM・supplier partを管理するinventory system。REST APIとpluginを持つ。 | Web/REST API、Python plugin。 | 活発に更新（2026-08-13）。 | **中**。部品masterと調達情報を外部systemに持つ場合の統合先候補。KiCad database libraryのbackendとして使う運用例が知られる。 | ACDの設計graphとどちらを正にするかは設計判断。KiCad連携の公式サポート範囲は未確認。 |

KiCadの**database library**（`.kicad_dbl`＋ODBC）は、CERN、InvenTree連携の双方で
使われている実運用パターンである。ライブラリの正を外部DBに置き、KiCad側はviewとして
参照する構造は、ACDの「設計グラフが正、KiCadは投影」という方針と整合しうる。ただし
ODBC driverと外部DBは実行環境依存が増えるため、決定論的ゲートで使う場合はdriver版、
DBスナップショットhash、接続設定を記録する必要がある。

## 4. KiCad MCP／AIエコシステム

以下はすべて「MCP」はJSON-RPC/stdio等のagent boundaryであり、MCP接続自体は
KiCadの決定的な検証保証を意味しない。各プロジェクトのGitHub READMEを
一次情報として確認した範囲を記録する。

| 名称／URL | 種別・license | 機能／自動化・形式 | 現状、関連度、未確認 |
|---|---|---|---|
| [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) | OSS。SPDX未確認。 | IPC API、`kicad-cli`、parserのhybrid。PCB/schematic、部品 sourcing等をMCPから扱う。 | README列挙のv2.4.1/v2.5.0（2026-07）以外を独立確認できず。**高**、比較・参考実装。 |
| [lamaalrajih/kicad-mcp](https://github.com/lamaalrajih/kicad-mcp) | OSS、SPDX未確認。 | Resources/tools/promptsを分離するKiCad MCP reference implementation。 | version/date/API全域は確認できず。**中**、MCP設計比較。 |
| [Seeed-Studio/kicad-mcp-server](https://github.com/Seeed-Studio/kicad-mcp-server) | OSS、SPDX未確認。 | KiCad 9+、schematic/PCB分析、pin-level net tracing、ERC/DRC via kicad-cli、device tree/test code generation。stdio。 | README取得で機能とKiCad 9+を確認。**高**、解析・検証worker。license/version不明。 |
| [salitronic/eda-agent](https://github.com/salitronic/eda-agent) | OSS、READMEにApache-2.0。 | Altium Designer persistent DelphiScript bridge、KiCad IPC backend。300+ tools、audit/design plan/validation。 | KiCad 9+ IPC、Altium AD20+ Windows。**高**、review/plan adapter。exact release/date未確認。 |
| [KiPilot](https://github.com/belaszalontai/kipilot-mcp) | OSS、SPDX未確認。 | KiCad 10.xのopen PCBへofficial kicad-python IPC。read-heavy、guarded mutation、stdio MCP。 | GUI process必須のlive workflow。**高**、安全なIPC adapter。version/date/license未確認。 |
| [Circuitron](https://github.com/Shaurya-Sethi/circuitron) | OSS、SPDX未確認。 | SKiDL RAGを使うrequirements→circuit generation pipeline。 | Python/LLM/RAG境界、出力形式・headless詳細不明。**中**、要求→回路比較。 |
| [Konnect](https://github.com/mixelpixx/Konnect) | OSS beta、SPDX未確認。 | Rust native KiCad 10 plugin。MCP stdio/HTTP、official IPC、schematic S-expression atomic write、kicad-cli export/check、部品検索、Freerouting。README取得時187 tools/18 toolsets。 | PCB editingはKiCad running/IPC、schematic writeはGUIなし可。**高**、toolset/guard設計の比較。beta、exact release/date/license未確認。 |
| [KiCad MCP Pro](https://github.com/oaslananka/kicad-mcp) | OSS、SPDX未確認。 | schematic/PCB/ERC/DRC/DFM/BOM/manufacturing review。read-only default、progressive disclosure、guarded write/release。 | MCPでheadless/GUIの混在。README取得時programmatic parity 76.3% badge。**高**。version/date/license未確認。 |
| [ProductOfAmerica/mcp-server-kicad](https://github.com/ProductOfAmerica/mcp-server-kicad) | OSS、SPDX未確認。 | schematic 40、PCB 29、symbol 5、footprint 4、project 24 tools。read/write、ERC/DRC、Gerber/drill/PnP/BOM/PDF/SVG/DXF/netlist。`uvx`起動。 | cwdからKiCad project自動検出。**高**、headless export・tool contract比較。release/date/license不明。 |
| [KiCad AI Assistant](https://github.com/paul356/KiCad-AI-Assistant) | OSS plugin、SPDX未確認。 | KiCad 10 action plugin内LLM chat＋embedded MCP。standalone `kcaa` MCPも掲げる。 | GUI pluginまたはstandalone MCP。KiCad schematic/PCB。**中〜高**。version/date/license不明。 |
| [DCENT Konduit](https://d-central.tech/dcent-konduit/) | OSS/サービス境界不明。license不明。 | KiCad MCP ecosystem engine、README列挙では570+ tools。 | 公開記事/landing page。実際のtool contract・headless・releaseは確認できず。**中**。 |

## 5. OSSエージェント

| 名称／URL | 種別・license | 実体・境界 | 現状／役割／未確認 |
|---|---|---|---|
| [boardsmith](https://github.com/ForestHubAI/boardsmith) | OSS、SPDX未確認。 | text prompt→KiCad schematic/BOM/firmware。9-stage pipeline、11 constraint checks。`--no-llm`でfull pipeline deterministic、no key/network。 | README取得で機能を確認。**最高**、deterministic synthesis比較。version/date/license不明、PCB layout範囲要確認。 |
| [EEschematic](https://github.com/eelab-dev/EEschematic) | OSS/研究、SPDX未確認。 | MLLMがSPICE netlistからanalog schematicを生成。VCoTで配置・配線を反復しeditable JSON-like output。 | GitHub READMEで確認。**中**、schematic visualization研究。KiCad互換、headless、release不明。 |
| [schem](https://github.com/Raf3-Tech/schem) | OSS、SPDX未確認。 | README §6列挙のprompt/EDA系プロジェクト。詳細機能を一次ページで確認できず。 | **低〜中**、比較対象。実体、format、version、license確認できず。 |
| [KiCadAI](https://github.com/dshills/KiCadAI) | OSS、SPDX未確認。 | KiCad AI支援プロジェクト。公開READMEの現行機能を本調査では取得できず。 | **中**、比較対象。API/CLI/format/version確認できず。 |
| [ReviewAI](https://github.com/Gyrych/ReviewAI) | OSS、SPDX未確認。 | hardware design review AIとして列挙。詳細一次情報を確認できず。 | **中**、review evidence比較。確認できず。 |
| [Fragua](https://github.com/mentasystems/fragua) | OSS。repo READMEにMITタグ。 | AI-native PCB。schematic→placement→routing→ERC/DRC→manufacturing DRC→fab-ready zip。独自 `pcb-script` DSL、決定的seed router/placer、clearance validator。 | README取得で、JLCPCB/PCBWay fab package、human click orderingを確認。**最高**、end-to-end比較。release/date、全license条項未確認。 |
| [kicad-agentic-studio](https://github.com/dionjerry/kicad-agentic-studio) | OSS/desktop、SPDX未確認。 | Electron/React UI、NestJS/LangGraph agent、KiCad files、ngspice、JLCPCB/DigiKey sourcing、MCP/Python。 | READMEはreal `.kicad_sch/.kicad_pcb`、Gerber/BOM、one-click manufacturingを掲げる。**高**。beta/実装成熟度・API・license不明。 |

## 6. 研究・ベンチマーク

| 名称／一次URL | 種別・license | 対象／入出力 | 現状・関連度・未確認 |
|---|---|---|---|
| [DeepPCB / RL routing, arXiv:2003.07897](https://arxiv.org/abs/2003.07897) | 研究。論文licenseの再利用条件は要確認。 | 強化学習によるPCB routing研究。入力はboard/routing state、出力はrouting policy/solution。 | 2020論文。**中**、探索候補と固定router/DRCを比較する基準。製造・MCAD評価は対象外。 |
| [AnalogCoder, arXiv:2405.14918](https://arxiv.org/abs/2405.14918) | 研究 | LLMによるanalog circuit designを生成・simulation・修復する系統。 | 論文と実験条件を読む必要があり、現行製品versionなし。**高**、generate→simulate→repairの評価対象。 |
| [OpenROAD](https://theopenroadproject.org/) | OSS EDA、licenseは各repo確認が必要 | RTL-to-GDS digital ASIC flow、placement/routing/timing/DRC等を自動化。 | PCBではないが完全自動EDA flowの代表。**中**、deterministic gate/flow orchestration類例。 |
| [HWE-Bench, arXiv:2603.18102](https://doi.org/10.48550/arxiv.2603.18102) | 研究/benchmark | promptからhardware schematic等を評価するbenchmark。 | README列挙では最高総合pass rate 8.15%。**高**、graph/verification benchmark。時点・実装版は論文固定。 |
| [pcbGPT, arXiv:2606.01188](https://arxiv.org/html/2606.01188v1) | 研究 | PCB design generation benchmark/agent。 | README列挙のpass@1 0.90/pass@5 1.00等は著者条件に依存。**高**。製造・実測は未評価。 |
| [PCB-Bench](https://github.com/digailab/PCB-Bench) | OSS benchmark、READMEはopen licensingを掲げるがSPDX exact未確認 | placement/routing reasoningをtext/image/real PCB artifactで評価。zero-shot datasets/evaluation scripts。 | GitHub README取得でICLR 2026 benchmarkを確認。**最高**、ACD regression benchmark候補。license exact/version未確認。 |

## 7. シミュレーション・検証

| 名称／URL | 種別・license | 機能／自動化境界・形式 | 関連度／状況 |
|---|---|---|---|
| [ngspice](https://ngspice.sourceforge.io/) | OSS、SPDX exact未確認 | SPICE simulator。CLI/shared library/WASM候補。netlist/model→waveforms/measurements。 | **高**、deterministic electrical gate。46系の2026-03情報はREADME列挙、正確なrelease確認は未実施。 |
| [Xyce](https://xyce.sandia.gov/) | OSS、Sandia license詳細要確認 | 大規模並列 SPICE-compatible simulator。netlist→waveforms。CLI/headless。 | **高**、worker検証器。version/license未確認。 |
| [LTspice](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html) | 無償 proprietary | SPICE GUI/バッチ機能。ネットリスト/モデル→waveform。 | **中**、user-installed external verifier。Redistribution/API/license制約を要確認。 |
| [QSPICE](https://www.qorvo.com/design-hub/calculators-simulation/qspice) | proprietary/freeware | mixed-signal SPICE simulator。GUI中心、script/batch詳細未確認。 | **中**。API/headless/license不明。 |
| [PySpice](https://github.com/PySpice-org/PySpice) | OSS、SPDX未確認 | Python interface to SPICE engines、netlist/model/measurements。 | **高**、Python adapter。ngspice engine version/provenanceを別記録要。release/license不明。 |
| [IBIS](https://ibis.org/) | standard/spec、spec licenseは別確認 | I/O buffer model standard。`.ibs` model→SI/PI simulation。 | **高**、model provenance/evidence。 |
| [Touchstone 2.1](https://ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf) | standard/spec | N-port S-parameter format、`.sNp`→SI analysis。 | **高**、周波数・port・engine versionをgateに記録。 |
| [openEMS](https://openems.de/) | OSS、SPDX未確認 | FDTD electromagnetic solver。geometry/material/excitation→fields/S-parameters。CLI/script可能。 | **高**、EM verification。mesh/solver convergenceを必須Evidenceにする。 |
| [scikit-rf](https://scikit-rf.org/) | OSS Python、SPDX未確認 | RF network analysis、Touchstone read/write、plots/calculations。 | **高**、postprocess/gate。 |
| [Renode](https://renode.io/) | OSS/commercial boundary、SPDX exact未確認 | virtual hardware/MCU/peripheral simulation、CLI/script。 | **中〜高**、firmware before hardware。 |
| [QEMU](https://www.qemu.org/) | OSS多license、SPDX exact要確認 | CPU/system virtualization/emulation、CLI。 | **中**、firmware/SoC model。real peripheral fidelityはモデル依存。 |
| [Elmer](https://www.elmerfem.org/) | OSS、license exact未確認 | multiphysics FEM、batch solver。mesh/material/BC→fields。 | **中**、thermal/mechanical worker候補。 |
| [Wokwi](https://wokwi.com/) | 商用サービス＋一部OSS境界 | browser MCU simulation、virtual peripherals、CLI/GitHub Actionsの範囲あり。 | **中〜高**、firmware/logic smoke test。実測代替ではない。 |
| [CircuitLab](https://www.circuitlab.com/) | 商用Web、proprietary | browser circuit schematic/simulation。 | **中**、interactive review。公開API/headless不明。 |
| [Falstad/CircuitJS](https://falstad.com/circuit/) | OSS/website、license exact未確認 | browser JavaScript circuit simulation。 | **中**、fast educational smoke test。API/production fidelity不明。 |
| [EveryCircuit](https://everycircuit.com/) | 商用、proprietary | interactive browser/mobile circuit simulation。 | **低〜中**、UX比較。headless/API不明。 |
| [CRUMB](https://www.crumbsim.com/) | 商用、proprietary | browser/interactive electronics simulation。 | **低〜中**、UX比較。headless/API不明。 |

## 8. 製造・ソーシング

| 名称／URL | 種別・license | 自動化・形式 | APIで見積／発注 | 関連度・注意 |
|---|---|---|---|---|
| [JLCPCB capabilities](https://jlcpcb.com/capabilities/pcb-capabilities) | 商用 | PCB capability/DFM仕様、Gerber/Drill/BOM/placement等をWebに投入。 | PCB capabilityページだけではAPIを確認できず。別の[JLC API Platform](https://api.jlcpcb.com/)はPCB pricing/order/tracking APIに加え、Components API（EDA/ERP連携による100万点規模の部品の実時間価格・在庫・仕様取得）を明記し、**見積・発注・tracking可**。アクセス申請が必要。 | **最高**。DFM profile/Evidence。API利用資格・契約・境界を確認必須。 |
| [PCBWay capabilities](https://www.pcbway.com/capabilities.html) | 商用 | PCB/assembly capability、Web quote。 | 公式partner API docsには`PcbQuotation`、`PlaceOrder`、`ConfirmOrder/Pay`、status queryがあるため、**partner APIで見積・発注フロー可**。api-key、sandbox/契約要。 | **最高**。manufacturing profile＋bounded ordering。 |
| [Nexar/Octopart](https://nexar.com/api) | 商用API | GraphQL、OAuth2。parts、pricing、inventory、lifecycle、offers、lead time。 | **検索・価格・在庫可**。発注APIではなくsupply data API。 | **最高**、sourcing Evidence。snapshot時刻・region・currencyを保存。 |
| [Digi-Key API](https://developer.digikey.com/) | 商用API | Product Information V4、part search/change notifications。 | 公式developer portalはAPI solutionsとordering automationを説明。**product情報とordering自動化の可能性はあるが、具体的発注endpoint/資格は要契約**。 | **高**。価格在庫の外部Evidence。 |
| [Mouser API](https://www.mouser.com/api-hub/) | 商用API | product search/data/inventory等のdeveloper API。 | API hubの公開範囲で具体的なautomated purchase可否は確認できず。**見積／発注は確認できず**。 | **高**、sourcing。 |

### 筐体・機械製造／見積API

| 名称／URL | 種別・license | 機能・形式 | 見積／発注API | 関連度・未確認 |
|---|---|---|---|---|
| [JLC3DP API](https://jlc3dp.com/help/article/jlc3dp-api)、[JLC API](https://api.jlcpcb.com/) | 商用 | STL/STP/STEP/OBJ/3MFのupload、pricing、3D print order/status。 | **可**。Pricing APIとOrdering APIを明記。ただしpartner審査・monthly volume等でaccess制限。 | **最高**。external irreversible order gate。 |
| PCBWay 3D print/CNC | 商用 | Web quote。 | PCBWay API docsはPCB API中心。3D print/CNCの公開自動見積・発注APIは**確認できず**。 | **中〜高**。手動 fallback。 |
| [Xometry Developer API](https://developer.xometry.com/reference) | 商用API | offers/jobs/files/webhooks。 | **可否を分ける**。公開docsはoffer/job情報取得、accepted offer後のjob import/webhookを示す。全自動の新規見積・発注権限はpartner契約依存で、公開ページだけでは断定不可。 | **高**。quote/order state webhook。 |
| Protolabs Network (Hubs) | 商用 | instant quote、CNC/3D print/manufacturing portal。 | 公開APIで自動見積・発注できることは**確認できず**。 | **中**、manual RFQ fallback。 |
| [Craftcloud](https://craftcloud3d.com/) | 商用 marketplace | network比較、instant quotes、3D print/CNC。 | 公開developer API/自動発注は**確認できず**。Web instant quoteとAPIは別物。 | **中**。price comparison external source。 |
| DMM.make 3D print | 商用 | 3D print upload/quote/order Web。 | 公開APIによる自動見積・発注は**確認できず**。 | **低〜中**。日本向けmanual fallback。 |
| [Slant3D API](https://www.slant3d.com/api) | 商用API | REST、3D printed manufacturing endpoint、quote/order/shipping/tracking。 | **可**。公式ページはinstant quote、place orders、track fulfillment、API keyを明記。 | **高**。automated local manufacturing候補。契約・materials/profile要確認。 |

### 8.1 製造ベンダークライアントとEDA→fab送信経路（2026-08-13追加調査）

§8はvendorのcapabilityと見積・発注APIを扱ったが、実際の設計→製造の経路には、
GUIクライアント、EDA plugin、vendor側DFM、非公式CLIといった別の層がある。その層の
自動化可能性とEvidence化可否を切り分けて記録する。

| 名称／一次URL | 種別・license | 実体・機能 | 自動化境界／入出力 | 最新状況（2026-08-13確認） | acd-agent関連度・役割 | 不確実性 |
|---|---|---|---|---|---|---|
| [JLCONE](https://jlcpcb.com/jp/download)（[英語版](https://jlcpcb.com/download)） | JLCPCB公式proprietaryクライアント、closed source | Windows／macOS（ARM・Intel）デスクトップ版とGoogle Play／App Storeモバイル版。PCB、PCBA、SMTステンシル、3Dプリント、CNC、板金、機構部品の発注を単一UIへ統合し、注文状態のpush通知、製造例外時のエンジニアとのライブチャット、アプリ限定割引（初回$104クーポン）を提供。 | 人間向けGUI／モバイル。注文・状態確認・問い合わせを一体化する。 | 公開は2025-08-25とされるが、根拠は第三者press release（2025-08-28）で二次情報。ヘルプセンターの「JLCONE Download and Installation」はmacOSインストールガイドのみ。 | **中**。agent自動化面ではなく、不可逆な発注を人手で確認するfallback経路と注文状態の可視化経路。自動化の正面は§8既出のJLC API Platform。 | ダウンロードページで版番号・changelog・checksum・署名情報・ライセンス条項を確認できず、配布binaryをEvidenceとしてpinできない。利用規約とデータ取り扱いは未確認。 |
| [JLC API Platform](https://api.jlcpcb.com/)（Components API） | 商用API、proprietary | EDAツールやERPと連携し、100万点規模の部品の実時間価格・在庫・仕様を取得するComponents APIを公開ページに明記。 | developer portalでアカウント登録し、無償のAPI access申請を行う。Components APIの具体的endpointは申請後の境界。 | §8既出のPCB／Stencil／3D Printing APIに加えてComponents APIを確認（2026-08-13確認）。 | **高**。§3.1のjlcparts（scrape）に対する公式データ経路の候補。 | 具体的endpoint仕様、rate limit、データ再配布条件、審査基準は申請しないと確認できない。 |
| [EasyEDA / LCSC / JLCPCB](https://easyeda.com/page/about) | proprietary Web EDA／SaaS | LCSCの部品カタログとJLCPCBの製造サービスを設計ツール内に統合。100万超の無料ライブラリ、API、script、Altium／KiCad／Eagle／PNG／DXF importを掲げ、OSHWLab、JLC3DP、JLCCNC、JLCMCも周辺に統合。 | Web GUI／cloud format。設計から部品選択・製造サービスへ接続するが、外部ゲートとの機械的な境界は未確認。 | 公式Aboutで機能と垂直統合を確認（2026-08-13確認）。 | **中**。設計から発注までを単一ベンダーで閉じる例で、設計graphを正、製造を外部境界とするACDとは対照的。 | 設計データのcloud・format依存、外部の決定論的ゲートやEvidence保存との接続可否、APIの範囲、data export／所有権条件は未確認。 |
| [Fabrication Toolkit（bennymeg）](https://github.com/bennymeg/Fabrication-Toolkit) | OSS、`Apache-2.0` | KiCad pcbnew plugin。JLCPCB向けGerber／BOM／CPLを生成し、footprint回転補正の対応表を内蔵。 | GUIに加えてCLIを持つ。`python3 -m plugins.cli -p /myProject/myBoard.kicad_pcb`で実行でき、GUIの全オプションをCLIでも利用可能。KiCad jobsetからも呼び出せる。`.kicad_pcb`→Gerber／BOM／CPL。 | 最新release `5.3.1`（2026-05-15）（2026-08-13確認）。 | **高**。fab固有のfabrication packageをheadless生成でき、入力hash→出力hashで決定論的ゲート化できる数少ないplugin。 | 回転補正tableの正しさはJLC側の運用に依存し、plugin版差で出力が変わりうるため、生成物hashだけでなくplugin版の固定が必要。 |
| [PCBWay Plug-in for KiCad](https://github.com/pcbway/PCBWay-Plug-in-for-Kicad) | OSS、`MIT` | ワンクリックでGerber、IPC-netlist、BOM、Pick and Placeをexportしuploadし、Save to Cartでカート投入まで進むKiCad plugin。KiCad 10対応。 | GUI plugin。`.kicad`設計→製造ファイルupload／cart投入。assembly発注にはMPNが必要で、schematicからのboard更新が前提。 | 最新release `v1.0.5`（2026-03-31）（2026-08-13確認）。 | **中**。発注の一歩手前（cart投入）までを自動化する例で、見積と発注の分離の実装バリエーション。 | headless実行境界は未確認。PCBWay partner API（§8既出）との機能重複関係も未確認。 |
| [AISLER Push for KiCad / Push for CLI](https://github.com/AislerHQ/PushForKiCad) | OSS、`MIT` | Gerberに加えてODB++をassembly・smart testの一次データとしてexportし、BOMとPick'n'Placeも送る。再pushすると同一projectの新revisionとしてサーバ側に保存される。 | KiCad plugin／CLI。board setupのtext variable `aisler_export_locally`でuploadせずZIPをローカル出力できる。Push for CLIはS3互換クライアントで組織ごとのtoken配下へputし、CI pipelineで利用できる。 | 最新release `0.3.2`（2026-04-09）、KiCad 10対応（2026-08-13確認）。公開API specはなく、個別access key発行運用。 | **高**。pushごとの製造側revision管理とODB++一次交換formatが、ACDのfab package投影設計の参考になる。 | quote/order stateの機械可読取得可否は未確認。認証情報のキー文字列は本台帳に転記しない。 |
| [Eurocircuits PCB / PCBA Visualizer](https://www.eurocircuits.com/user-guides/visualizer-user-guides/) | 商用Webツール、proprietary SaaS | アップロードした製造データからdigital twinを作り、700超のDRC／DFM ruleと970超のpre-defined buildupに照らして製造可否を自動判定。PCB CheckerとAssembly Checkerで指摘を確認でき、VisualizerまたはCAD側で修正する。 | Web UI／アカウント。製造データ→digital twin／DFM判定。公開APIによる自動実行は確認できず。 | PCB Visualizerは2012年、PCBA Visualizerは2017年提供開始（2026-08-13確認）。 | **高**。vendor側DFM gateとして成熟した公開例で、ACDのDFM profile比較対象。 | 判定ruleは非公開のblack boxで、結果を外部で再現検証できない。 |
| [Seeed Studio OPL KiCad Library](https://github.com/Seeed-Studio/OPL_Kicad_Library) | OSS、`CC-BY-SA-4.0` | Seeed Fusion PCBAサービスのOpen Parts Library（OPL）に対応するsymbol／footprint。Seeed Fusionチームとコミュニティが保守。 | Git clone／KiCad library。fabが実装できる部品集合を設計側へ配布する。 | 最終push 2026-06-23、releaseなし（2026-08-13確認）。 | **中〜高**。Digi-Key atomic partsやjlcpartsと同系で、fab実装可能部品集合のライブラリ化を比較できる。 | 設計成果物向け例外条項は確認できず、素のCC-BY-SA-4.0。改変・再配布時のshare-alike影響を個別確認し、版はcommit hashで固定する必要がある。 |
| [KiCost](https://github.com/hildogjr/KiCost) | OSS、`MIT` | KiCad BOMから複数distributorの価格・在庫を横断取得し、cost spreadsheetを生成。 | CLI／Python。BOM→価格・在庫snapshot／spreadsheet。 | 最新release `v1.1.21`（2026-07-08）（2026-08-13確認）。 | **高**。取得時刻・通貨・地域つきcost／availability snapshotをartifact化する先行例。 | distributorごとのAPI key要否・利用規約は個別確認。web scrape経路では規約リスクがあり、保存メタデータの範囲は実装依存。 |
| [InteractiveHtmlBom](https://github.com/openscopeproject/InteractiveHtmlBom) | OSS、`MIT` | KiCad、EasyEDA、Eagle、Fusion360、Allegroの基板データから実装作業向け対話的HTML BOMを生成。 | KiCad plugin。基板データ→HTML BOM。 | 最新release `v2.11.2`（2026-05-24）、最終push 2026-07-12（2026-08-13確認）。 | **中**。決定論的に生成できるassembly補助artifactで、実装・検査Evidenceに利用できる。 | headless／CLI実行の範囲は今回確認していない。 |
| [jlcpcb-mcp（Eyalm321）](https://github.com/Eyalm321/jlcpcb-mcp) | OSS、`MIT` | jlcpartsのSQLite catalog検索、`wmsc.lcsc.com`からの実時間在庫・価格・datasheet取得、公式JLC Open API経由のGerber upload、見積、注文明細／状態、注文作成を計28 toolで提供。 | MCP server。注文作成toolは`JLCPCB_ENABLE_ORDERS`既定offのgateで塞がれ、見積・uploadは資格情報のみで動く。 | 最新release `v0.3.3`（2026-06-03）（2026-08-13確認）。 | **高**。不可逆な発注をgateで分離する最も近い実装例。 | star 1程度の小規模個人実装で運用・監査実績はなく、そのまま依存する対象ではない。`wmsc.lcsc.com`は非公式endpointで規約適合性未確認。env flag一つでは承認ID・最終artifact固定に不足。 |
| [hatlabs/jlcpcb-cli](https://github.com/hatlabs/jlcpcb-cli) | ライセンス未確認（LICENSEファイルなし、GitHub license APIもnull） | ブラウザログインでJLCPCBのWeb内部APIを叩き、注文batch一覧、PCB／SMT／3DP明細、コスト内訳、personal parts inventoryをJSON取得。 | 非公式CLI。ブラウザ認証→注文・実績JSON。公式API keyは使わない。 | 最終push 2026-07-03、releaseなし（2026-08-13確認）。 | **中**。製造結果のclosed loopに必要な実コスト・納期・状態を機械可読に取り出す例。 | 非公式経路のため仕様変更で壊れ、規約適合性も不明。ライセンス未確認のためACDへの取り込み・参照実装としての流用は保留。 |
| [tracespace](https://github.com/tracespace/tracespace) | OSS、`MIT` | Gerber／drillからSVG renderingを生成。 | CLI／renderer。Gerber／drill→SVG。 | 既定branchは`v5`、最終push 2025-01-20で更新停滞、latest releaseはAPI取得不可（2026-08-13確認）。 | **中**。fab packageの視覚検証を決定論的に行うrenderer候補。 | 最新Gerber表現への追随は未確認。 |

この層は「GUIクライアント（JLCONE、EasyEDA）」「EDA plugin（Fabrication Toolkit、
PCBWay、AISLER）」「vendor側DFM（Eurocircuits Visualizer）」「非公式CLI/MCP
（jlcpcb-cli、jlcpcb-mcp）」に分かれる。自動化とEvidence化に適するのはCLIを持つ
ものだけであり、ACDでは発注のような不可逆操作はJLCONEのようなGUI経路を人手の確認点
として残しつつ、機械が回すのは見積・DFM・package生成までに限り、そこで生成物hashと
tool版を記録する切り分けが妥当である。§3.1のjlcpartsとkicad-jlcpcb-toolsもこの層と
地続きだが、部品ライブラリ側の調査として同節に記録している。

## 9. コラボレーション・版管理

| 名称／URL | 種別・license | 機能／境界 | 関連度・未確認 |
|---|---|---|---|
| [AllSpice](https://www.allspice.io/) | 商用SaaS、proprietary | Hardware Git-like collaboration、design files、review/versioning。 | Web/SaaS。公開API・差分semantic・headless gateの全範囲は確認できず。**高**、revision/review比較。 |
| [CADLAB.io](https://cadlab.io/) | 商用/サービス、proprietary | CAD version control/review/collaboration。 | GUI/Web。対象EDA、API、現行statusは確認できず。**中**、hardware diff比較。 |

## 10. 機械CAD・AI/MCP

| 名称／URL | 種別・license | 機能／自動化境界・形式 | 関連度・状況 |
|---|---|---|---|
| [FreeCAD](https://github.com/FreeCAD/FreeCAD) | OSS LGPL/GPL等のcomponent license確認要。 | Parametric MCAD、Python console/API、headless可能なbatch範囲、STEP/IGES/STL等。 | **最高**。governed MCAD worker。FreeCAD exact current release/license matrixは未確認。 |
| [FreeCAD MCP (neka-nat)](https://github.com/neka-nat/freecad-mcp) | OSS、SPDX未確認。 | FreeCADをMCPから操作する先行実装。 | MCP/FreeCAD bridge。version/date/license不明。**高**。参照実装。 |
| [sandraschi/freecad-mcp](https://github.com/sandraschi/freecad-mcp) | OSS、READMEでlicenseは本調査未確認。 | FastMCP＋FreeCAD、headless document/export、REST dashboard、CFD/OpenFOAM/FluidX3D、PrusaSlicer連携。ports 10944/10945/10946、46 toolsをREADMEで確認。 | **高**。headless geometry→diagnostics pipeline比較。exact version/license未確認。 |
| [tessalabs-space/freecad-mcp](https://github.com/tessalabs-space/freecad-mcp) | READMEにMIT。 | parametric CAD、drafting、annotations、renders、sweeps、CAE handoff（Elmer/CalculiX/OpenFOAM/DEM）。 | MCP/FreeCAD addon/RPC。**高**。typed tool surface。release/date未確認。 |
| [theosib/FreeCAD-MCP-Server](https://github.com/theosib/FreeCAD-MCP-Server) | OSS、SPDX未確認。 | live FreeCAD bridge。document graph、object/shape topology、sketch diagnostics、tracked recompute diff、script/screenshot。 | stdio MCP→TCP addon。**最高**、deterministic diagnostics/recompute evidence。license/version不明。 |
| [Autodesk Fusion MCP sample](https://github.com/AutodeskFusion360/FusionMCPSample) | Autodesk sample、licenseはrepo確認要。 | Fusion 360 APIとMCPをつなぐsample。 | Fusion GUI/application/API境界。STEP/mesh等はFusion依存。**高**、commercial MCAD integration比較。 |
| [Zoo/KittyCAD Text-to-CAD API](https://zoo.dev/docs/developer-tools/api/ml) | 商用/API、proprietary | Text-to-CAD/ML API、CAD generation、REST/WebSocket系。出力はCAD geometry/STEP等の製品仕様依存。 | API/headless。料金・model version・exact formatsは要契約。**高**、cloud geometry generation比較。 |
| [CADAM](https://github.com/Adam-CAD/CADAM) | OSS/研究、SPDX未確認。 | AI/CAD generation project。詳細機能・現行APIを本調査で確認できず。 | **中**、参照対象。version/license/format不明。 |
| [PartCAD](https://github.com/partcad/partcad) | OSS、SPDX未確認。 | Digital-thread code-CAD package。CadQuery/build123d/OpenSCAD、STEP/BREP/STL/3MF/OBJ、KiCad PCB、DXF/SVG、render cache、LLM providers。 | Python/CLI、headless compile/cache。**高**、part/evidence registry・ECAD/MCAD bridge。version/license未確認。 |
| [KiCad StepUp](https://github.com/easyw/kicadStepUpMod) | OSS FreeCAD workbench、SPDX exact未確認。 | KiCad board/parts→FreeCAD、STEP/IGES、VRML; footprint alignment; interference/collision; PCB edge pull/push。 | FreeCAD GUI/workbench＋macro、STEP AP214等。headless完全対応は未確認。**最高**、ECAD-MCAD projection/clearance。 |

## 11. code-CAD基盤と筐体agent

| 名称／URL | 種別・license | 実体／境界／形式 | 関連度・状況 |
|---|---|---|---|
| [agentcad](https://github.com/jdilla1277/agentcad)、[agentcad.dev](https://agentcad.dev/) | OSS/サービス境界、SPDX未確認。 | Agentがbuild123d/CadQuery Pythonを書く。CLIが実行、STEP、STL/GLB/OBJ mesh、PNG、geometric metrics（volume/dimensions/validity/face-edge counts）、validation/diffをstructured JSON stdoutで返す。 | CLI/headless/browser preview。**最高**、deterministic geometry worker。release/version/licenseは未確認。 |
| [cad-khana](https://github.com/cyberchitta/cad-khana) | OSS、SPDX未確認。 | Build123d wrapper。`khana build/check/view/draw/diff`、STL/STEP、`diagnostics.json`（interference, clearance, wall thickness, overhang）、assertions→build failure、engineering drawing PNG。 | CLI、headless build/check。**最高**、決定論的MCAD gateとdiagnostics artifact。version/license未確認。 |
| [build123d](https://github.com/gumyr/build123d) | OSS、SPDX未確認。 | Python parametric BREP on Open Cascade、3D print/CNC/laser、STEP/STL等。 | Python/headless、viewer任意。**最高**。version/license詳細未確認。 |
| [CadQuery](https://github.com/CadQuery/cadquery) | OSS、SPDX未確認。 | Python parametric CAD on OCCT/OCP。 | Python/headless、STEP/standard CAD。READMEはPython 3.9-3.12 supportを記載。**高**。 |
| [OCP](https://github.com/CadQuery/OCP) / [OCCT](https://dev.opencascade.org/) | OSS、OCCT license境界確認要 | Python wrapper/geometry kernel。BREP/STEP/IGES等のkernel operations。 | Native/Python bindings、headless。**最高**、validity/boolean/measurement worker。 |
| [trimesh](https://github.com/mikedh/trimesh) | OSS、SPDX未確認。 | Python triangular mesh processing, repair, analysis, export。STL/PLY/OBJ/GLB等。 | Python/headless。**高**、mesh metrics/printability precheck。 |
| [OpenSCAD](https://openscad.org/) | OSS GPL系、正確なSPDXを配布時確認。 | declarative `.scad` CSG、CLI render/export、STL/3MF/CSG等。 | CLI/headless。**高**、simple enclosure generator。 |
| Other [build123d MCP](https://github.com/pzfreo/build123d-mcp) | OSS、SPDX未確認。 | MCP toolboxでmodel step、render、measure、repair、STEP/STL/SVG/DXF export。 | MCP＋Python/headless。**高**、agent geometry interface。 |

## 12. ECAD/MCAD連携標準

| 名称／URL | 種別 | できること／自動化境界 | acd-agent用途・未確認 |
|---|---|---|---|
| [prostep ivip IDX](https://www.ecad-mcad.org/) | 標準 | ECAD/MCAD incremental design exchange、変更・合意・差分を扱う協調交換。 | **最高**、board/enclosure change contract。具体的なOSS parser/現行schema versionは未確認。 |
| IDF 2.0/3.0 | 交換format/標準 | PCB outline、component placement/keepout等のECAD↔MCAD簡易交換。 | **高**、legacy projection。STEPほど豊かな形状ではない。 |
| STEP AP242 | ISO standard | product manufacturing information、CAD assembly/geometry/metadata交換。 | **最高**、canonical artifactのMCAD projection。実装kernelが必要。 |
| [Siemens Solid Edge PCB Collaboration](https://www.siemens.com/) | 商用 | ECAD/MCAD collaboration、PCB/assembly exchange。 | **中〜高**、commercial interoperability比較。具体URL/APIは本調査で未特定。 |
| [Altium MCAD CoDesigner](https://www.altium.com/documentation/altium-codesigner/installing-configuring/autodesk-fusion) | 商用 | Altium WorkspaceをbridgeにFusion等へPCB assemblyをpull/push、change exchange。 | GUI add-in＋cloud workspace。**高**、双方向協調の比較。REST/headless、license不明。 |
| [Fusion 360 Electronics](https://www.autodesk.com/solutions/ecad-and-mcad-software) | 商用統合 | ECAD/MCADを同一Fusion platformで扱い、board/component dataをMCADで検証。 | Web/desktop SaaS。**高**、integrated product comparison。API/料金不明。 |

## 13. 筐体×基板の自動生成事例

| 事例 | 実体・形式 | 自動化／限界 | 関連度 |
|---|---|---|---|
| [Ultimate-Box-Maker](https://github.com/jbebel/Ultimate-Box-Maker) | OpenSCAD parametrized `.scad`。PCB size/marginsからbox、panels、holesを生成。 | 手編集またはOpenSCAD CLI。PCB-centricだがKiCad live link/verificationは確認できず。 | **高**、最低限のboard→enclosure generator比較。 |
| KiCad StepUp | KiCad board/footprints→FreeCAD/STEP、edge pull/push、collision check。 | 交換・レビューはできるが、agentが制約から筐体を自動合成する製品ではない。 | **最高**、projection/verification。 |
| OpenSCAD box libraries / generators | OpenSCAD code-CAD ecosystem。 | CLIで決定的にmeshを出せるが、component height/connector clearanceを自動で読み込む共通契約は確認できず。 | **高**、simple parametric enclosure。 |
| PartCAD / agentcad / cad-khana | code-CAD＋structured metrics/diagnostics。 | board geometryを入力へ入れるadapterと固定profilesは自前。 | **最高**、ACDの筐体worker候補。 |
| Fusion/CoDesigner | integrated ECAD/MCAD assembly collaboration。 | 既存設計のpull/push・reviewが中心。promptからケースを自動確定する公開機能は確認できず。 | **高**、commercial benchmark。 |

## 14. slicer／3D-print検証自動化

| 名称／URL | 種別・license | CLIと検証可能性 | 関連度・注意 |
|---|---|---|---|
| [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer) | OSS、license exactはrepo確認要 | CLIはGUIなしで使用可能。STL/3MF等→G-code/3MF。support、layer、overhang等はprofile・slice結果から検査可能だが、一般的な「engineering wall thickness pass/fail」APIを単独で保証するものではない。 | **高**。fixed profileでprintability gate。engine/profile/version/input hashを記録。 |
| [CuraEngine](https://github.com/Ultimaker/CuraEngine) | OSS、license exact未確認 | C++ console。`CuraEngine slice -j settings.json -l model.stl -o out.gcode`。 | **高**、headless slicer。support/overhangの意味はsettings依存。 |
| OrcaSlicer CLI | OSS、license exact未確認 | CLIでsettings/filamentをloadしslice、3MF/G-codeをexportする運用。公式CLI documentationの取得は未確認、community referenceでcommand shapeを確認。 | **中〜高**。CLIは使えるが、公式のversion-specific契約を固定して採用すべき。 |

## 15. OpenHands／OpenHands SDKを使うhardware/CAD事例

OpenHands Software Agent SDKの公式READMEは「codeを扱うagent」を対象とし、
local workspaceまたはDocker/Kubernetes Agent Serverを説明している
（[公式SDK](https://github.com/OpenHands/software-agent-sdk/)）。公式リポジトリ、
公式ドキュメント、一般検索を調査したが、公開された**ハードウェア設計・PCB・
MCAD専用の完成事例は確認できなかった**。

OpenHandsを汎用orchestration layerとしてKiCad、FreeCAD、agentcad、
`kicad-cli`、slicerを外部workerとして呼ぶことは技術的には可能だが、これは
既存先行事例の実績ではなく、ACDの統合案（**推測**）である。OpenHands SDK自体が
ECAD/MCADのgeometry、netlist、DFMの意味論を持つことは確認できず、typed artifact、
deterministic gate、approval-bound irreversible operationはACD側で定義する必要がある。

## 16. acd-agentの差別化ギャップ候補

1. **ECADとMCADのcanonical graph:** 既存例はKiCad、STEP、IDF、FreeCADを
   交換・投影する。一方、要求、電気トポロジー、部品provenance、mechanical
   envelope、keepout、Evidenceを一つのversioned graphにまとめた公開実装は
   確認できない。
2. **決定論的gateの標準化:** `kicad-cli`、DRC、SPICE、FreeCAD recompute、
   slicerは個別に自動化できる。しかし、tool version、input hash、output hash、
   convergence、uncertainty、approvalを共通envelopeにまとめる例は少ない。
3. **製造結果のclosed loop:** fab package生成やquoteの公開例はある。hatlabs/jlcpcb-cliは
   注文履歴・コスト内訳・在庫を機械可読に取得する部分的な先行例だが、非公式Web API経由で
   ライセンスも未確認であり、取得した実績を設計graphへ戻す経路は確認できない。実製造の
   DFM修正、納期、歩留まり、実測を設計graphへ戻す公開end-to-end実装も確認できない。
4. **筐体×基板の同時制約:** StepUp/CoDesignerは協調交換、Ultimate Box Makerは
   parametric box、agentcad/cad-khanaはgeometry diagnosticsを提供する。
   電気制約と機械制約を同時に探索し、根拠付きで修復する仕組みは未成熟である。
5. **MCPの安全な書き込み:** KiCad MCPは増えているが、read-only default、
   guarded mutation、approval ID、revision conflict、reopen verificationを
   一貫して義務化する標準は確認できない。
6. **部品・3Dモデルの出所:** SnapMagic、Ultra Librarian、Nexar等はデータ源である。
   しかし、採用時点のdatasheet、lifecycle、stock、footprint/3D hashを設計revision
   に固定する横断的な公開実装は確認できない。
   CERN KiCad Librariesは、nightly生成pipelineのprovenanceをcommit messageに記録し、
   `CHECKSUMS`によるファイル単位hashとdatabase library形式を備える最も近い先行例である。
   一方、設計revisionへの採用時点のdatasheet、lifecycle、stock、hashの固定までは確認できない。
7. **benchmarkの製造・実測不足:** HWE-Bench、pcbGPT、PCB-Benchは生成とreasoningの
   評価を進めているが、fab、assembly、bring-up、measurementまでを含む公開benchmarkは
   確認できない。
8. **API-first orderingの安全境界:** JLC、PCBWay、Slant3D等には自動化APIがある。
   jlcpcb-mcpは注文作成toolを`JLCPCB_ENABLE_ORDERS`の既定offで塞ぐ最も近い実装例だが、
   小規模な個人実装であり、見積→承認ID→最終artifact固定→status webhookを分離した
   汎用ゲートには至っていない。
9. **製造可能性の実体検査:** slicerはG-codeを生成できるが、ケースの肉厚、overhang、
   support、嵌合、ねじ、insert、公差を一つの標準診断にまとめた例はcad-khana等の
   新しい実装に限られる。
10. **オープンで交換可能なagent runtime:** Flux、Altium、Fusionは強力だが
    proprietaryである。ACDには、OpenHandsをruntimeとし、KiCad、FreeCAD、外部solverを
    replaceable evidence workerとして組み合わせる余地がある。

## 17. 筐体×基板協調設計で公開実装が到達していない点

以下の点について、公開実装が一つの設計契約として閉じている例は確認できない。

- 基板外形、mounting holes、connector keepout、component heightを読み、
  parametric enclosureを生成するだけでなく、MCAD kernelでinterference、clearance、
  wall、draft、fastener、assembly sequenceまでgateし、その結果をPCB placementと
  requirementsへ自動反映すること。
- ECAD/MCAD交換の各変更をIDX等で因果的に記録し、古いSTEPや3D modelに基づく
  Evidenceをstaleとして無効化すること。
- board vendorのcapability、3D-print material/profile、CNC toleranceをgeometry
  constraintsとして同じgraphに置くこと。
- quote APIの価格、納期、shipping、taxと、PCB、assembly、enclosureを含むtotal
  order costを同じ最終gateで扱うこと。
- 生成形状を見た目だけで合格にせず、kernel validity、mass properties、printability、
  fit fixture、reopen/recomputeを機械的に判定すること。
- live GUI MCPを使う場合にも、dirty document、undo stack、external modification、
  version mismatch、reconnect後のstateを検出すること。

## 18. 決定論的ゲートに使える外部ツール一覧

| Gate | 推奨外部ツール | 入力→証拠 | 決定性／注意 |
|---|---|---|---|
| KiCad schema/plot/DRC/ERC | KiCad 10 `kicad-cli` | `.kicad_sch/.kicad_pcb`→reports/Gerber/drill/BOM | pinned binary/profileでCI可能。GUI IPCと分離。 |
| PCB route | Freerouting | DSN→SES→KiCad reopen/DRC | seed/settings/version固定。SES単独を合格証拠にしない。 |
| Schematic parser/patch | kiutils/kicad-skip | S-expression→normalized graph/diff | parser versionとinput hashを固定。 |
| Electrical simulation | ngspice/Xyce/PySpice | netlist/model→waveform/measurement | model provenance、convergence、tolerances必須。 |
| SI/RF | scikit-rf/openEMS/IBIS/Touchstone | geometry/S-parameter→S-params/fields | mesh、ports、frequency、modelを記録。 |
| Firmware smoke | Renode/QEMU/Wokwi | firmware＋virtual board→test logs | virtual modelのcoverageを実機と混同しない。 |
| MCAD validity/geometry | OCCT/OCP、FreeCAD | STEP/script→validity、volume、bbox、recompute | kernel/toolchain固定、fail closed。 |
| MCAD diagnostics | cad-khana/agentcad | build123d/CadQuery→diagnostics JSON/STEP/mesh | assertion、interference、clearance、wall、overhangをartifact化。 |
| ECAD/MCAD exchange | KiCad StepUp、IDF、IDX、STEP AP242 | board/assembly↔STEP/IDF/IDX | exchange success≠fit pass。reopen＋collision gate。 |
| Mesh/print precheck | trimesh | STL/OBJ/3MF→watertight/normals/metrics | mesh validityのみで製造可否を断定しない。 |
| Slicing | PrusaSlicer/CuraEngine/OrcaSlicer | STL/3MF＋pinned profile→G-code/3MF/log | layer/support/overhang等をprofileとともに保存。 |
| PCB fab quote/DFM | JLCPCB API、PCBWay partner API | Gerber/zip＋profile→quote/DFM/order state | quoteとorderを分離。orderはapproval ID必須。 |
| 3D print quote/order | JLC3DP、Slant3D、Xometry partner API | STEP/STL/3MF→quote/order/webhook | 契約・access、価格snapshot、最終hashを記録。 |
| Component evidence | Nexar/Octopart、Digi-Key、Mouser | MPN/query→price/stock/lifecycle | time/region/currency/credentials scopeを保存。 |
| fab package生成 | Fabrication Toolkit CLI | `.kicad_pcb`→Gerber/BOM/CPL | plugin版と回転補正tableを固定。 |
| Gerber視覚検証 | tracespace | Gerber/drill→SVG | 更新停滞に注意し、renderの一致を製造可否の証拠にしない。 |
| BOM cost snapshot | KiCost | BOM→価格・在庫spreadsheet | 取得時刻・通貨・distributor資格情報のscopeを保存。 |

## 19. まとめ

公開実装の重心は、次の層に分かれている。

- code/DSLからKiCadへ投影する層
- KiCad/FreeCADをMCPで操作する層
- `kicad-cli`、SPICE、CAD kernel、slicerで検証する層
- fab/sourcingのquote APIを扱う層

**要求、電気、機械、製造を一つの型付き設計graphと決定論的Evidenceで結び、
承認付きの不可逆操作まで閉じる公開実装は確認できない。** これはacd-agentが狙える
差別化候補である。

ただし、これは「他に絶対存在しない」という証明ではない。各商用製品の非公開API、
契約者限定機能、同名で検索できなかったPHDL等は確認できない。採用前には、次を個別に
再確認する必要がある。

- 対象version/commit
- SPDX
- データ再配布条件
- API利用規約
- 特許・輸出・製造契約

## 20. ライセンス境界まとめ（追加調査）

以下は採用候補に絞り、LICENSE本文または公式のライセンス記述を取得した結果を追記した
ものである。`取得できず`は、本文取得を試したURLも併記した。

「SPDX」はリポジトリ全体の単一ライセンスを意味しない場合がある。特にKiCad、QEMU、
FreeCAD、OCCT、スライサは同梱依存物・データ・プラグインに別ライセンスがあるため、
リリース単位のNOTICE/SBOM確認が必要である。

### 20.1 対象別の取得結果と暫定分類

| ツール | SPDX | 分類 | 最新版と日付（2026-08-11確認） | 根拠URL | 配布・結合の境界メモ |
|---|---|---|---|---|---|
| KiCad本体／`kicad-cli` | `GPL-3.0-or-later`を主ライセンスとして扱うが、ソースツリーに第三者・例外ライセンスあり | GPL | `10.0.5`, 2026-07-22 | [LICENSE/COPYING](https://github.com/KiCad/kicad-source-mirror/blob/master/COPYING.txt)、[release API](https://api.github.com/repos/KiCad/kicad-source-mirror/releases/latest) | ACDから`kicad-cli`を別プロセスとして実行し、成果物だけを受け取る形は、ACD本体へのライブラリ結合を避けられる実用的な境界。ただしKiCad binaryを再配布するならGPL本文、NOTICE、第三者依存の同梱条件を満たす必要がある。法的判断は必要。 |
| `kicad-python` / KiCad IPC | KiCad本体と同じ配布物のライセンス体系。binding単独のSPDXは取得できず | GPL系／要構成確認 | KiCad `10.0.5`, 2026-07-22 | [KiCad Python docs](https://docs.kicad.org/kicad-python-main/kicad.html)、[source](https://github.com/KiCad/kicad-source-mirror) | Python packageをACDへimportするのではなく、KiCad側IPCへ接続する構成が境界を明確にする。Python bindingの単独再配布条件は取得できず、法的判断が必要。 |
| freerouting | `GPL-3.0-only` | GPL | GitHub Releasesの最新版は**取得できず**（試行: [releases/latest](https://github.com/freerouting/freerouting/releases/latest)、[API](https://api.github.com/repos/freerouting/freerouting/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/freerouting/freerouting/master/LICENSE) | `freerouting` JAR/CLIを外部プロセスで呼び、DSN/SESだけ交換する形が実用的。ACDへJava codeをimport/linkする場合はGPLのcombined-work義務を法務確認する。 |
| kiutils | `GPL-3.0-only` | GPL | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/mvnmgrx/kiutils/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/mvnmgrx/kiutils/master/LICENSE) | Python importはGPL結合・配布論点が生じるため、MIT想定のACDへ直接組み込む前に法的判断が必要。隔離worker/外部プロセス化だけではPython packageのライセンス問題が自動解決するとは限らない。 |
| kicad-skip | `LGPL-2.1-only` | LGPL | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/psychogenic/kicad-skip/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/psychogenic/kicad-skip/master/LICENSE) | LGPLはGPLより緩やかだが、import、改変、静的結合、配布物のrelink条件を確認する必要がある。外部プロセス化はさらに単純な境界だが、実装の著作権・依存物は個別確認。 |
| KiCanvas | `MIT`のLICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/theacodes/kicanvas/main/LICENSE)） | 未確認 | 最新releaseは**取得できず**（[releases](https://github.com/theacodes/kicanvas/releases)） | [repository](https://github.com/theacodes/kicanvas) | browser viewerを独立projectionとして使う候補。ただしMITは未確定なので、ACDへのimport・bundle前にLICENSEファイルを再取得する。 |
| diodeinc/pcb | `MIT` | MIT | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/diodeinc/pcb/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/diodeinc/pcb/main/LICENSE) | MITのため、通常はimport/外部プロセス双方が実用的。ただし依存 package と生成KiCad artifactのライセンスは別確認。 |
| atopile | `MIT` | MIT | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/atopile/atopile/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/atopile/atopile/main/LICENSE) | CLIを外部プロセスで使うのが最も境界明瞭。MITなのでimportも候補だが、依存solver・部品データ・出力ライブラリは別確認。 |
| tscircuit | `MIT` | MIT | 最新releaseは**取得できず**（試行: [releases/latest](https://api.github.com/repos/tscircuit/tscircuit/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/tscircuit/tscircuit/main/LICENSE) | MIT。TypeScript package import、CLI、生成artifactのいずれも実用候補。依存monorepo packageごとのlicense確認は必要。 |
| SKiDL | `MIT` | MIT | `2.3.0`, 2026-07-28 | [LICENSE本文](https://raw.githubusercontent.com/devbisme/skidl/master/LICENSE)、[release API](https://api.github.com/repos/devbisme/skidl/releases/latest) | MITだが、Python依存とKiCad libraryは別物。直接importまたは隔離Python workerの両方が実用的。 |
| boardsmith | `AGPL-3.0-only` | AGPL | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/ForestHubAI/boardsmith/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/ForestHubAI/boardsmith/main/LICENSE) | ACDへPython/JS codeをimportすることは避けるべき候補。外部CLI/別サービスとして利用する場合も、配布・ネットワーク利用・改変版提供のAGPL適用範囲は法務確認が必要。 |
| Fragua | LICENSE本文は指定URLで**取得できず**（READMEのMIT表示のみ） | MIT想定だが未確定 | `v1.1.0`, 2026-07-28 | [LICENSE試行](https://raw.githubusercontent.com/mentasystems/fragua/main/LICENSE)、[release API](https://api.github.com/repos/mentasystems/fragua/releases/latest) | READMEのMIT表示だけでは確定根拠にならない。外部binaryとして使う場合でも、再配布するなら実際のLICENSE・依存・bundled librariesを確認する。 |
| ngspice | リポジトリの`COPYING`本文は取得できたが、版ごとの構成・第三者コードを含むため単一SPDXは**確定できず** | 混在／要SBOM | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/ngspice/ngspice/releases/latest)） | [COPYING](https://raw.githubusercontent.com/ngspice/ngspice/master/COPYING) | `ngspice` executableを外部プロセスで呼ぶのが推奨境界。libngspiceをimport/linkする場合は構成・GPL/BSD部品・配布義務を法務確認する。 |
| Xyce | `BSD-3-Clause`は公式説明で示されるが、LICENSE本文URLは**取得できず** | BSD | 最新releaseは**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/Xyce/Xyce/master/LICENSE)、[releases](https://github.com/Xyce/Xyce/releases)） | [公式サイト](https://xyce.sandia.gov/) | 外部CLIが実用的。BSDならimportも通常は可能だが、実際の依存・third-party noticeを確認してから確定する。 |
| PySpice | `GPL-3.0-or-later`（LICENSE本文の取得URLは**取得できず**） | GPL | 最新releaseは**取得できず**（試行: [releases/latest](https://api.github.com/repos/PySpice-org/PySpice/releases/latest)） | [repository](https://github.com/PySpice-org/PySpice) | ACDへPython importする前にGPL結合を法務確認。PySpiceを隔離workerで使い、ngspiceを外部プロセスにする構成がより境界明瞭。 |
| openEMS | `GPL-3.0-or-later`とされるがLICENSE本文URLは**取得できず** | GPL想定／未確定 | `v0.0.36`, 2023-10-22 | [LICENSE試行](https://raw.githubusercontent.com/thliebig/openEMS-Project/master/LICENSE)、[release API](https://api.github.com/repos/thliebig/openEMS-Project/releases/latest) | solver executableを外部workerとして使うのが実用的。Python binding/importやmodified distributionはlicense確認を先行する。 |
| scikit-rf | `BSD-3-Clause`と公式package metadataで扱われるがLICENSE本文URLは**取得できず** | BSD | 最新releaseは**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/scikit-rf/scikit-rf/master/LICENSE)、[releases](https://github.com/scikit-rf/scikit-rf/releases)） | [repository](https://github.com/scikit-rf/scikit-rf) | BSDであることが確定すればPython importが実用的。ただし今回は本文未取得なので、採用時にPyPI sdistまたはrepo LICENSEを再確認する。 |
| Renode | `MIT` | MIT | `v1.16.1`, 2026-02-16 | [LICENSE本文](https://raw.githubusercontent.com/renode/renode/master/LICENSE)、[release API](https://api.github.com/repos/renode/renode/releases/latest) | MIT本体はimport/外部実行双方が実用的。ただしLICENSE本文が明記する各libraryの個別licenseをSBOMで追跡する。 |
| QEMU | `GPL-2.0-or-later`（QEMU emulator本体。firmware等は別ライセンス） | GPL／混在 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/qemu/qemu/releases/latest)） | [license clarification](https://raw.githubusercontent.com/qemu/qemu/master/LICENSE) | QEMU executableを外部プロセスで呼ぶのが実用的。libvirt/QEMU librariesをimport/linkする場合、GPL本体と同梱firmwareの個別条件を法務確認する。 |
| Elmer | `GPL-2.0-or-later`想定だがLICENSE本文URLは**取得できず** | GPL想定／未確定 | 最新releaseは**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/ElmerCSC/elmerfem/devel/LICENSE)） | [repository](https://github.com/ElmerCSC/elmerfem) | solverを外部プロセス化。library import、solver module配布、modified binary配布は法務確認。 |
| FreeCAD | `LGPL-2.1-only`を主ライセンスとして扱うが、workbench/third-partyは別ライセンス | LGPL／混在 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/FreeCAD/FreeCAD/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/FreeCAD/FreeCAD/master/LICENSE) | FreeCAD executable/workerを外部プロセスで呼ぶ構成が境界明瞭。Python modulesをACDへimport、静的結合、FreeCADの改変配布はLGPLのrelink・notice等を法務確認する。 |
| KiCad StepUp | LICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/easyw/kicadStepUpMod/master/LICENSE)） | 未確認 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/easyw/kicadStepUpMod/releases/latest)） | [repository](https://github.com/easyw/kicadStepUpMod) | FreeCAD workbenchとしてimportするため境界が複雑。licenseを確定するまでACDへの同梱・再配布を避け、利用者環境の外部addonとして扱う案も法務確認が必要。 |
| build123d | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/gumyr/build123d/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/gumyr/build123d/dev/LICENSE) | Python import、CLI worker、生成STEP/STLのいずれも実用的。OCCT/OCP等の依存licenseは別確認。 |
| CadQuery | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/CadQuery/cadquery/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/CadQuery/cadquery/master/LICENSE) | importと外部workerの双方が実用的。OCP/OCCTの依存を別にSBOM化する。 |
| OCP | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/CadQuery/OCP/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/CadQuery/OCP/master/LICENSE) | Python bindingのimportが実用候補。ただしwrapperに含まれるOCCT binaryのlicense・exception・配布条件を別確認。 |
| OCCT | `LGPL-2.1-only WITH OCCT-exception-1.0`（公式配布のLGPL＋OCCT exceptionとして扱う） | LGPL＋例外 | 最新版は**取得できず**（試行: [official download](https://dev.opencascade.org/release)） | [OCCT licensing](https://www.opencascade.com/license/) | OCCT exceptionは通常のLGPLと同一ではない。静的/動的結合、modified kernel、著作権表示、exceptionが適用されるファイル範囲を法務確認する。OCP経由のimportでも自動的に全条件が消えるわけではない。 |
| trimesh | `MIT` | MIT | `5.0.0`, 2026-08-01 | [LICENSE本文](https://raw.githubusercontent.com/mikedh/trimesh/main/LICENSE.md)、[release API](https://api.github.com/repos/mikedh/trimesh/releases/latest) | import、worker、mesh artifact処理とも実用的。optional依存は別license確認。 |
| OpenSCAD | `GPL-2.0-or-later`想定だが本文取得URLは**取得できず** | GPL想定／未確定 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/openscad/openscad/releases/latest)） | [COPYING試行](https://raw.githubusercontent.com/openscad/openscad/master/COPYING) | `openscad` CLIを外部プロセスで呼ぶのが実用的。ACDにlibraryとしてimport/linkする形は避け、再配布時は本体・依存のGPL条件を確認する。 |
| agentcad | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/jdilla1277/agentcad/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/jdilla1277/agentcad/main/LICENSE) | CLI/worker利用・Python runtime importとも候補。build123d/CadQuery/OCCT依存のlicenseを別管理する。 |
| cad-khana | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/cyberchitta/cad-khana/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/cyberchitta/cad-khana/main/LICENSE) | CLI外部workerが境界明瞭。内部build123d/CadQuery依存のlicenseと、生成diagnosticsの著作権条件は別確認。 |
| PartCAD | LICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/partcad/partcad/main/LICENSE)） | 未確認 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/partcad/partcad/releases/latest)） | [repository](https://github.com/partcad/partcad) | READMEの機能だけではimport/re-distribution可否を確定しない。license確定まで外部環境のCLIとしても採用判断を保留する。 |
| build123d-mcp | `Apache-2.0` | permissive | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/pzfreo/build123d-mcp/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/pzfreo/build123d-mcp/main/LICENSE) | MCP serverを別プロセスで呼ぶのが自然。Apache-2.0なので同梱/importも候補だが、MCP依存・build123d依存を別確認。 |
| Ultimate-Box-Maker | LICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/jbebel/Ultimate-Box-Maker/master/LICENSE)） | 未確認 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/jbebel/Ultimate-Box-Maker/releases/latest)） | [repository](https://github.com/jbebel/Ultimate-Box-Maker) | OpenSCAD sourceをACDに同梱・改変する前にlicenseを確定する。外部OpenSCADで利用するだけでも、source templateの再配布条件は法務確認。 |
| PrusaSlicer | `AGPL-3.0-or-later` | AGPL | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/prusa3d/PrusaSlicer/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/prusa3d/PrusaSlicer/master/LICENSE) | ACDへlibrary importは避けるべき。`prusa-slicer` executableを外部プロセスで呼ぶ場合は実用的だが、binaryをacd-agent distributionへ同梱・改変する際のAGPLと依存licenseを法務確認。 |
| CuraEngine | `AGPL-3.0-or-later` | AGPL | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/Ultimaker/CuraEngine/releases/latest)） | [LICENSE本文](https://raw.githubusercontent.com/Ultimaker/CuraEngine/main/LICENSE) | `CuraEngine` CLIを外部プロセスで使うのが実用的。AGPL codeをACDへimport/linkすることは避け、再配布・改変時のsource offerとNOTICEを法務確認。 |
| OrcaSlicer | `AGPL-3.0-or-later`想定だがLICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/SoftFever/OrcaSlicer/main/LICENSE)） | AGPL想定／未確定 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/SoftFever/OrcaSlicer/releases/latest)） | [repository](https://github.com/SoftFever/OrcaSlicer) | AGPLを前提に、CLI外部実行のみを採用候補とする。本文・同梱PrusaSlicer由来コード・profilesのlicense確定が先。 |
| PCB-Bench | LICENSE本文は**取得できず**（試行: [LICENSE](https://raw.githubusercontent.com/digailab/PCB-Bench/main/LICENSE)） | 未確認 | 最新releaseは**取得できず**（試行: [releases/latest](https://github.com/digailab/PCB-Bench/releases/latest)） | [repository](https://github.com/digailab/PCB-Bench) | benchmark code/data/model weightsをACDへimport・再配布する前に、コードとデータセットを分離してlicense確認。 |
| CERN KiCad Libraries | `CERN-OHL-P-2.0`（`LICENSE`、`LICENSES/`、`.reuse/dep5`で明示。dep5のcopyrightは2024-2025 CERN） | permissive（CERN-OHL-P） | tag・releaseはなくmaster nightly更新、最新commit `2026-08-13T01:05Z`（bot commit）（2026-08-13確認） | [LICENSE](https://gitlab.com/ohwr/cern-kicad-libs/-/raw/master/LICENSE)、[.reuse/dep5](https://gitlab.com/ohwr/cern-kicad-libs/-/raw/master/.reuse/dep5) | permissive variantなので設計・再配布とも制約が緩いが、ライブラリデータの再配布時はCERN-OHL-P-2.0の表示義務と免責（section 5）を守る。3D model・datasheetは非同梱で、別出所のデータを混ぜる場合はライセンスが分かれる。 |
| KiCad公式ライブラリ（`kicad-symbols`/`kicad-footprints`/`kicad-packages3D`） | `CC-BY-SA-4.0`＋設計向け例外 | CC-BY-SA＋例外 | `kicad-symbols`の最新tag `10.0.5`（2026-07-15）（2026-08-13確認） | [kicad-symbols/LICENSE.md](https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/master/LICENSE.md) | 例外により設計成果物へのshare-alike波及は生じない読み方が公式見解だが、ライブラリを集合として再配布・改変再配布する場合はCC-BY-SA義務が残る。 |
| kicad-library-utils | `GPL-3.0`（COPYING本文取得） | GPL | tagなし、master更新（2026-08-11活動）（2026-08-13確認） | [COPYING](https://gitlab.com/kicad/libraries/kicad-library-utils/-/raw/master/COPYING) | KLCチェックは外部プロセス（CLI）実行に限定し、ACDへimport結合しない。 |
| kicad-footprint-generator | README記載 `GPL-3.0-or-later`（ファイル単位の例外あり、LICENSE本文は未取得） | GPL | tagなし、master更新（2026-08-13確認） | [README](https://gitlab.com/kicad/libraries/kicad-footprint-generator/-/raw/master/README.md) | 生成器は外部プロセス実行。生成されたfootprintの再配布条件は別途確認。 |
| Digi-Key KiCad library | `CC-BY-SA-4.0`＋KiCadと同文の設計向け例外 | CC-BY-SA＋例外 | 最終push 2024-03-16、releaseなし（2026-08-13確認） | [LICENSE.md](https://github.com/Digi-Key/digikey-kicad-library/blob/master/LICENSE.md) | 更新停滞、atomic partsの調達属性は取得時点付きsnapshotとして扱う。 |
| Espressif KiCad Libraries | `CC-BY-SA-4.0`＋設計向け例外 | CC-BY-SA＋例外 | 最新release `3.2.1`（2026-07-24）（2026-08-13確認） | [LICENSE.md](https://github.com/espressif/kicad-libraries/blob/main/LICENSE.md) | PCM addonをversion固定で利用。 |
| SparkFun KiCad Libraries | LICENSE本文を**取得できず**（GitHub license APIも404。試行: [LICENSE.md](https://raw.githubusercontent.com/sparkfun/SparkFun-KiCad-Libraries/main/LICENSE.md)） | 未確認 | 最新release `v9.0.0`（2025-10-17）（2026-08-13確認） | [LICENSE.md試行](https://raw.githubusercontent.com/sparkfun/SparkFun-KiCad-Libraries/main/LICENSE.md) | ライセンス確定まで同梱・再配布は保留。 |
| Horizon EDA pool | `CC-BY-SA-4.0`＋設計向け例外 | CC-BY-SA＋例外 | 最終push 2026-06-26（2026-08-13確認） | [LICENSE.md](https://github.com/horizon-eda/horizon-pool/blob/master/LICENSE.md) | KiCadと異なるライブラリモデルのため、変換して取り込む場合は帰属表示を維持。 |
| jlcparts | `MIT`（コードのみ。収集データはJLCPCB/LCSC由来） | MIT | releaseなし、最終push 2026-08-13（2026-08-13確認） | [repository](https://github.com/yaqwsx/jlcparts) | コードはMITだが部品データの再配布可否はLCSC/JLCPCB側条件。 |
| kicad-jlcpcb-tools | `MIT` | MIT | 最終push 2026-07-30（2026-08-13確認） | [repository](https://github.com/Bouni/kicad-jlcpcb-tools) | KiCad GUI plugin前提。 |
| InvenTree | `MIT` | MIT | 活発更新（2026-08-13確認） | [repository](https://github.com/inventree/InvenTree) | 外部サービスとしてAPI連携する形が境界明瞭。 |
| JLCONE | proprietary（配布条項未確認） | proprietary | 公開日は2025-08-25とされるが第三者press release由来（2026-08-13確認） | [ダウンロード](https://jlcpcb.com/jp/download) | 配布binaryの版・checksum・署名・ライセンス条項が確認できないため、ACDへの同梱・pinは保留。人手fallbackとして利用する。 |
| EasyEDA／LCSC／JLCPCB | proprietary SaaS | proprietary | 現行版・日付は未確認（2026-08-13確認） | [EasyEDA About](https://easyeda.com/page/about) | SaaS利用を前提とし、設計データのcloud／format境界、export・所有権条件を確認するまでACDへの結合・再配布は行わない。 |
| Eurocircuits PCB／PCBA Visualizer | proprietary SaaS | proprietary | PCB Visualizerは2012年、PCBA Visualizerは2017年提供開始（2026-08-13確認） | [Visualizer user guides](https://www.eurocircuits.com/user-guides/visualizer-user-guides/) | Webサービスとして外部DFMを利用する。ruleがblack boxで公開APIも未確認のため、判定結果だけを再現可能なEvidenceとみなさない。 |
| Fabrication Toolkit | `Apache-2.0` | permissive | 最新release `5.3.1`（2026-05-15）（2026-08-13確認） | [repository](https://github.com/bennymeg/Fabrication-Toolkit) | CLIを外部プロセス実行するかimportする境界は比較的明瞭。回転補正tableとplugin版を固定し、生成packageのhashを保存する。 |
| PCBWay Plug-in for KiCad | `MIT` | permissive | 最新release `v1.0.5`（2026-03-31）（2026-08-13確認） | [repository](https://github.com/pcbway/PCBWay-Plug-in-for-Kicad) | pluginは同梱・外部実行とも候補だが、GUI前提でheadless境界は未確認。Save to Cartは発注前の人手確認点に留める。 |
| AISLER PushForKiCad | `MIT` | permissive | 最新release `0.3.2`（2026-04-09）（2026-08-13確認） | [repository](https://github.com/AislerHQ/PushForKiCad) | plugin／CLIは外部プロセス利用候補。個別access keyと非公開API境界を分離し、pushごとのrevisionをEvidence化する。 |
| Seeed Studio OPL KiCad Library | `CC-BY-SA-4.0` | CC-BY-SA（設計成果物向け例外なし） | 最終push 2026-06-23、releaseなし（2026-08-13確認） | [repository](https://github.com/Seeed-Studio/OPL_Kicad_Library) | 素のCC-BY-SA-4.0のため、設計成果物向け例外のあるKiCad公式とは異なる。同梱・改変再配布はshare-alike影響を確認するまで保留する。 |
| KiCost | `MIT` | permissive | 最新release `v1.1.21`（2026-07-08）（2026-08-13確認） | [repository](https://github.com/hildogjr/KiCost) | CLI／importとも候補。distributorごとのAPI key・規約と、価格・在庫snapshotの取得時刻等を分離記録する。 |
| InteractiveHtmlBom | `MIT` | permissive | 最新release `v2.11.2`（2026-05-24）、最終push 2026-07-12（2026-08-13確認） | [repository](https://github.com/openscopeproject/InteractiveHtmlBom) | CLI生成artifactとして同梱・外部実行とも候補。入力hashと生成tool版を保存する。 |
| jlcpcb-mcp | `MIT` | permissive | 最新release `v0.3.3`（2026-06-03）（2026-08-13確認） | [repository](https://github.com/Eyalm321/jlcpcb-mcp) | MCPを外部プロセス実行する候補。`wmsc.lcsc.com`は非公式endpointで、注文gateも汎用承認境界としては不足する。 |
| hatlabs/jlcpcb-cli | ライセンス未確認（LICENSEなし、GitHub license APIもnull） | 未確認 | 最終push 2026-07-03、releaseなし（2026-08-13確認） | [repository](https://github.com/hatlabs/jlcpcb-cli) | ライセンス未確認・非公式Web API経路のため、ACDへの取り込み・同梱・参照実装としての流用は保留。 |
| tracespace | `MIT` | permissive | 既定branch `v5`、最終push 2025-01-20、latest releaseはAPI取得不可（2026-08-13確認） | [repository](https://github.com/tracespace/tracespace) | CLI／rendererとして利用候補だが更新停滞に注意。SVG renderは製造可否判定の代替にしない。 |

### 20.2 acd-agentでの暫定採用方針

これは法的結論ではなく、実装境界を決めるための保守的な設計方針である。

- **GPL/AGPLでimport結合を避けるべきもの:** freerouting、kiutils、
  boardsmith、PySpice、QEMU、OpenSCAD、PrusaSlicer、CuraEngine、
  OrcaSlicer（AGPLは本文未取得のため暫定）、およびGPL系の可能性がある
  openEMS、Elmer。KiCad/FreeCADも本体のbindingを直接import/linkするより、
  まず`kicad-cli`、FreeCAD batch、solver CLIを外部プロセス化する。
- **外部プロセス呼び出しなら実用的なもの:** KiCad/`kicad-cli`、
  freerouting、ngspice、Xyce、openEMS、QEMU、Elmer、FreeCAD、
  OpenSCAD、PrusaSlicer、CuraEngine、OrcaSlicer。外部プロセス化は
  ライセンス義務を消すものではないが、ACDのMIT想定コードとのlibrary
  combined-work論点を減らし、ツールbinary、NOTICE、依存SBOMを分離管理しやすい。
  kicad-library-utils（GPL）は外部プロセス側で扱い、CERN KiCad Librariesは
  permissiveなデータとして利用できる。
- **permissiveなplugin／CLI群:** Fabrication Toolkit、AISLER PushForKiCad、
  PCBWay plugin、KiCost、InteractiveHtmlBom、tracespace、jlcpcb-mcpは
  Apache-2.0またはMITで、外部プロセス実行にもimportにも障害が小さい。
- **同梱・参照を保留するもの:** Seeed OPLは設計成果物向け例外のない
  CC-BY-SA-4.0のため同梱・再配布を保留する。hatlabs/jlcpcb-cliは
  ライセンス未確認のため、参照実装としての利用も保留する。
- **importの第一候補:** diodeinc/pcb、atopile、tscircuit、SKiDL、
  build123d、CadQuery、OCP、trimesh、agentcad、cad-khana、
  build123d-mcp、Renode、scikit-rf。CERN KiCad Librariesもデータ利用の候補。
  ただし、各依存・生成データ・商用
  libraryのライセンスを解消した後に採用する。

GPL/AGPLの「外部プロセスなら必ず問題ない」という意味ではない。ネットワーク
提供、binaryの同梱、改変、配布、プラグイン、IPC境界が著作権法上どう評価される
かは利用形態・法域に依存するため、製品配布前に法的判断を取得する。

## 21. 配置・配線へのAI／LLM適用（2026-08-16追加調査）

本節は、[`ai-physical-design.md`](ai-physical-design.md)の方針根拠となる事例を、証拠の種別と
確度を分けて記録する。既存節（§2商用AI ECAD、§4KiCad MCP／AI、§6研究・benchmark、§10MCAD）に
記載済みの事例は重複させず、本節では「配置・回転・配線の探索と、その検証構造」に絞る。

### 21.1 証拠種別の区分

| 区分 | 意味 | 合格根拠としての扱い |
|---|---|---|
| 査読論文 | 会議・雑誌の査読を経た報告 | 手法選択の根拠にできる。ACDでの再現は別途必要 |
| preprint | arXiv等の未査読公開 | 仮説として扱う。数値は独立検証していない |
| benchmark | 公開データ・評価コードのある測定 | 能力限界の根拠にできる。評価設計の偏りは残る |
| OSS実装 | 動作するコードが公開されている | 構造の参考にできる。品質・保守性は別評価 |
| ベンダー主張 | 製品ページ・press release | 実現可能性の示唆にとどまる。独立再現なし |
| 二次情報 | 第三者記事のみ | 事実として引用しない |

### 21.2 LLMによる配置・制約生成

| 事例 | 種別 | 構造 | ACDへの含意 |
|---|---|---|---|
| [ModuPlace](https://yhhan.com/PDFs/ModuPlace_paper.pdf) | 論文（査読状況は本調査で未確認） | LLMがモジュール分解と制約グラフを作り、配置最適化は従来手法が実行 | L1宣言層／L2探索層の分離と同型。ACDの三層分離の主要根拠 |
| [LLM-augmented PCB placement refinement](https://doi.org/10.1145/3804601.3804665) | 査読論文（ACM DOI） | LLMが衝突の優先順位付けと修復戦略を選び、幾何調整はheuristicが行う | 「LLMは優先順位、幾何は決定論器」の裏付け |
| [LLM-Orchestrated PCB Design](https://doi.org/10.5281/zenodo.19440163) | preprint（Zenodo、実験検証はfuture workと明記） | LLMを回路意図から形式的配置制約への意味変換層に置く提案 | 提案の枠組みは近いが、効果は未実証。ACDでも効果主張はしない |
| [AnalogCoder](https://arxiv.org/abs/2405.14918)（§6にも記載） | preprint | 生成→シミュレーション→修復の反復 | 修復ループには外部評価器が必要という一般則の例 |

### 21.3 能力限界を示すbenchmark

| 事例 | 種別 | 読み取り |
|---|---|---|
| [PCB-Bench](https://github.com/digailab/PCB-Bench)（§6にも記載） | benchmark（ICLR proceedings PDFあり） | text／multimodal／実PCB成果物の推論を評価し、空間・制約推論に大きな弱点が残ることを報告。座標・角度の提案を決定論的ゲートで検証する判断の主要根拠 |
| HWE-Bench、pcbGPT（§6に記載） | benchmark／preprint | 生成とreasoningの評価にとどまり、fab・実装・bring-up・実測を含まない。ACDの実測ゲートを代替しない |

### 21.4 商用のAI配置・配線（ベンダー主張）

| 事例 | 種別 | 主張されている構造 | 注意 |
|---|---|---|---|
| [Quilter](https://www.quilter.ai/product/technology) | ベンダー主張 | 物理駆動のAI（強化学習を含むとされる）で複数レイアウト候補を生成し、物理・製造検証を通す | 内部アルゴリズム、検証範囲、再現性は非公開。§2にも記載 |
| [DeepPCB](https://deeppcb.ai/) | ベンダー主張＋[関連研究](https://arxiv.org/abs/2003.07897) | クラウドでのAI配置・配線。RL routingの研究が併存 | 製品と論文の対応関係は未確認 |
| [Cadence Allegro X AI](https://www.cadence.com/en_US/home/company/newsroom/press-releases/pr/2023/cadence-introduces-allegro-x-ai-accelerating-pcb-design-with.html) | ベンダー主張 | 生成AIを従来の物理設計アルゴリズムと解析へ組み合わせる | 数値（設計時間短縮等）は独立検証なし。§2にも記載 |
| [Flux Auto Layout](https://docs.flux.ai/tutorials/auto-layout) | ベンダー主張＋公開ドキュメント | AIが反復的に配線し、保護されたtrace／viaは変更せず、結果は取り消し可能な形で適用 | 「既存成果物の保護」と「可逆適用」はACDの探索にも採用すべき設計。§2にも記載 |

共通する構造は「AIが候補を作り、既存の物理設計アルゴリズムと物理検証が絞る」であり、
LLMが単独で最終配線を確定する製品は確認できない。

### 21.5 コード駆動・solver接地のAI設計

| 事例 | 種別 | 構造 | ACDへの含意 |
|---|---|---|---|
| [JITX](https://docs.jitx.com/en/latest/essentials/design/index.html)、[jitx-skills](https://github.com/jitx-inc/jitx-skills) | ベンダー主張＋OSS資材 | 設計を検査可能なコードとして表現し、生成・検証を分ける | 投影とゲートの構造と整合。agent資材の配布形態も参考になる |
| [Onshape FeatureScript MCP](https://www.ptc.com/en/news/2026/onshape-launches-featurescript-mcp-server) | ベンダー主張（press release） | 自然言語からFeatureScriptを作成・テスト・デバッグ | AIにコードを書かせ、実行と検証はCADエンジンが担う形 |
| [Zoo Zookeeper](https://zoo.dev/research/zookeeper) | ベンダー主張＋研究ページ | 対話CADでコードと形状を検査しながら設計レビュー | 視覚だけで閉じない構造の商用例 |
| Embodied CAD（[preprint](https://arxiv.org/html/2606.31252v1)）、Arko-T（[preprint](https://arxiv.org/html/2606.30429v1)）、[CAD-HLLM](https://proceedings.mlr.press/v304/zuo26a.html) | preprint／査読論文 | LLMが型付きCAD操作を選び、厳密カーネルが実行し、solverフィードバックで修復 | MCADレーンでも「提案はLLM、判定はカーネル」を採る根拠 |

### 21.6 探索ヒューリスティックのLLM生成

| 事例 | 種別 | 読み取り |
|---|---|---|
| [FunSearch](https://www.nature.com/articles/s41586-023-06924-6) | 査読論文（Nature） | LLMと系統的評価器を組み合わせ、bin packing等のヒューリスティックをコードとして発見。**評価器が本体**である |
| [AlphaEvolve](https://arxiv.org/abs/2506.13131v1) | preprint | 実行と自動評価に接地したLLM主導の進化的コード生成 |
| [Evolution of Heuristics](https://proceedings.mlr.press/v235/liu24bs.html) | 査読論文（ICML） | 組合せ最適化のヒューリスティック設計をLLMで進化させる |
| [OPRO](https://arxiv.org/abs/2309.03409v2) | preprint | LLMが過去の解とスコアから次の解を提案する。明示的な評価器が前提 |
| [AlphaChip](https://www.nature.com/articles/s41586-024-08032-5) | 査読論文（Nature） | RLによるチップフロアプラン。graph状態と明示的目的関数（配線長・混雑・密度） |

ACDでこの系統を採るなら、生成物は「commitされたコード」であり、通常のlint・型検査・
テスト・golden task回帰の対象とする。生成器の出力をその場で信じて回す構成は採らない。
RL系（AlphaChip、DeepPCB）は学習環境と計算資源を要するため初期ターゲット外とし、追跡のみ行う。

### 21.7 AIレビュー実装から得られる限界

| 事例 | 種別 | 読み取り |
|---|---|---|
| [boardroom](https://github.com/lluisestape-upc/boardroom) | OSS実装（品質・保守性は未評価） | Evidence必須の専門agent、tool laneの強制、構造化finding、限定的な討論、render画像による視覚レビュー。著者自身が検出率の限界を報告しており、視覚レビュー単独では合格にできない |
| [mcp-pcb-emcopilot](https://github.com/RFingAdam/mcp-pcb-emcopilot) | OSS実装 | Gerber/ODB++/IPC-2581/STEP等のparserと物理ベース検査toolをMCPで提供 | 「parseできる」ことと「製造可否を判定できる」ことを分けて扱う必要がある |
| [KiCad AI Assistant](https://github.com/paul356/KiCad-AI-Assistant)（§4にも記載） | OSS実装 | KiCad plugin＋MCP tool | GUI前提の書き込み境界はACDの承認・ゲート契約と別に検討する |

### 21.8 未確認事項

- 商用製品の内部アルゴリズム、検証範囲、成功率は非公開であり、本節の主張は独立検証していない。
- 2026年公開のpreprint（Embodied CAD、Arko-T、LLM-Orchestrated PCB Design、AlphaEvolve）は
  査読状況を確認していない。数値は引用せず、構造の参考としてのみ扱う。
- 回転刻み（90度以外の実装可否、CPL回転規約との整合）について、公開の実測比較は確認できなかった。
  ACD側の実測が必要な未決事項である。
- 代理指標（HPWL、混雑度）と実配線・DRC結果の相関を、PCB規模で公開測定した資料は確認できなかった。

## 本台帳の使い方

- ツールを採用するときは、本台帳の記述だけを根拠にせず、対象versionの一次情報を再確認する。
- 「確認できず」は解消済みとは扱わず、そのまま未決事項として管理する。
- ライセンス、契約、特許の最終判断は本台帳では行わず、必要な専門家・権利者への確認を行う。
