# 研究結論

> 詳細な調査資料はgit履歴に残し、ここではACDの決定に影響した結論だけを保持する。

## prior art

信頼性を担保するには生成と判定を分離し、独立再読込とfail-closedを組み合わせる必要がある。
この結論をL1決定論的ゲート、L2操舵、L3観測の三層境界とEvidence契約へ反映した。

## reliability practices

自動ゲート、AIレビュー、工程出口を相互補完させ、AIレビューに合否権限を与えない。
unknownや未実行は停止側へ倒し、`Evidence.supports_pass(revision)`を唯一のpass authorityとした。

## qc tools

Q7/N7は観察と修正計画の手法であり、代理指標や自然文所見を合否根拠にしない。
投影レビューは入力から再生成し、投影編集を正へ逆流させない。

## tool selection

KiCad、FreeRouting、CADなどの外部ツールは版・入力・出力を独立に確認し、能力不明を
fail-closedとする。SDKの汎用tool採否はACDゲートの決定権を変更しない。

## ecad domain notes

電気設計はnet、pin、stackup、座標、製造出力を別々の投影と再読込で確認する。
ERC/DRC、routing、Gerber/drill、BOM/CPLの契約をACD固有の決定論的責務として保持した。

## ai physical design

LLMは要求分解、候補生成、観察、修正案に使い、配置・配線候補は幾何合法化とゲートで
確認する。代理スコアや探索agentの出力だけで合格にしない。

## algorithmic music (theme song)

Strudel（TidalCyclesのJS移植、AGPL-3.0-or-later）、TidalCycles・FoxDot・Sardine・
SuperCollider・ChucK（GPL）、Sonic Pi、Gibber・Glicol（MIT）、music21（BSD）、
mido／pretty_midi、ACE-Step・YuE（Apache-2.0 GPU生成モデル）、MusicGen（重みCC-BY-NC）、
Stable Audio Open（Community License）を比較した。GPL/AGPLのimport結合禁止、再現性、
標準ライブラリ完結を満たすのは自前MIDI書き出しだけであり、Strudel等の再生環境依存形式は
生成しない。作曲はLLMが構造化JSON（調・テンポ・音符列・ドラム）で提案し、範囲・識別子・
時間軸のcontract検査を通った提案だけを決定論的にMIDIへレンダリングする。提案が無い場合は
graph hashをseedとするcomposerへfallbackする（ADR-0048）。

## MPW shuttle services

将来構想「ASIC製造（MPWシャトル）」（[`../roadmap-future.md`](../roadmap-future.md)）の前提として、
OpenSUSI-MPWと世界のMPW／シャトルサービスを2026-09-07時点の一次情報で比較した。

OpenSUSI-MPW（<https://www.opensusi.org/mpw-service>）は、NPO OpenSUSIが東海理化のNDAフリー
1µm CMOS（TR-1um、Apache-2.0 PDK）で運営する国内限定シャトルである。1注文¥200,000（税抜）で
die 2.5×2.5mm²・ユーザ領域1.8×1.8mm²・16pin DIP×5個、最大63枠、GDSII締切はMPW 2026が
2026/9/18、DryRun TESTが2026/10/1。設計repoは`OpenSUSI/TR-1um_MPW_template`をforkして
GitHubでpublic化することが必須で、`info.yaml`（`gds.top_cell`、`pdk.repo/ref/dir`、
`lvs.netlist_only`、`mdp.file`）と`src/<top>.gds`・`src/<top>.cir`を置くと、GitHub Actionsの
headless KLayoutがprecheck（top cell一致、top-level cell唯一、dbu、領域内）→DRC→LVS→
MDP（Drawing layer→Mask layer変換）を実行する。締切まで何度でも再Submitできる。

| サービス | 国 | プロセス／PDK | 単位・価格（公開情報） | 提出方式 | 公開義務 | 返却 |
|---|---|---|---|---|---|---|
| OpenSUSI-MPW | 日 | TR-1um（1µm CMOS、Apache-2.0） | ¥200,000／枠、63枠、国内限定 | テンプレfork＋GitHub Actions＋Entry Form | 必須 | 16pin DIP×5 |
| ISHI会版OpenMPW（OpenSUSI-TR10-1） | 日 | TR-1um | 無料（スポンサー提供、ハンズオン相乗り） | GitHub相乗りrepo | 必須 | OpenSUSI枠を分割 |
| Tiny Tapeout | 英／国際 | SKY130、IHP SG13G2、GF180MCU | tile課金（約160×100µm≒1000ゲート）、早期割引、年4回程度 | テンプレ（Wokwi／Verilog／Analog）＋GitHub Actions＋repo URL登録 | 実質必須（Apache-2.0テンプレ） | devkit PCB（COB含む）、6〜12か月 |
| ChipFoundry chipIgnite（旧Efabless） | 米 | SKY130（Caravel） | $14,950／project、予約金$500、最少20参加者 | GitHub repo＋precheck CI | 不要 | packaged。Google無償OpenMPWは終了 |
| IHP Open-Silicon MPW | 独 | SG13G2（130nm SiGe BiCMOS）、SG13CMOS5L | 面積課金 SG13G2 2,800€/mm²、CMOS5L 1,302〜1,500€/mm²（最低90mm²到達で900€/mm²）、公費の無料枠あり | IHP-Open-DesignLibへPR、DRC必須、OSS EDA互換必須 | Apache-2.0公開で最安（非公開は20%引き） | bare die 40個、QFN実装オプション |
| wafer.space | 米 | GF180MCU | 1 slot＝19.67mm²×1,000 die、Run 1は$40k目標で成立 | 自動提出、自己サインオフ（DRC/LVS/ERC/antenna） | 不要 | bare die／COB／wafer |
| Europractice mini@sic | 欧 | TSMC・GF・IHP・UMC・X-FAB・ST | 面積課金（例: TSMC 65LP 最低1mm² 3,691€割引、GF 12LP+ 33,000€/mm²） | NDA、商用PDK | 不要 | 学術割引あり |
| MOSIS 2.0 | 米 | TSMC・Intel・Samsung・SkyWater・GF・Tower、GaN/GaAs/InP | 個別見積 | NDA | 不要 | 米国政府系中心 |
| Muse Semiconductor | 米 | TSMC全ノード（Shared／Full block） | 個別価格表 | NDA | 不要 | 大学・スタートアップ |
| CMC Microsystems | 加 | TSMC・GF 12LP（$37,050/mm²学術）・AMS 0.35（$998/mm²、最低10mm²） | 面積課金 | NDA | 不要 | 学術サブスク割引 |
| 東大d.lab/VDEC | 日 | ROHM 0.18µm（年4回）ほか | 定価表、東大が請求 | GDS-II、Web提出時DRC | 不要 | 大学・高専限定、民間直接設計不可 |
| IDEC（韓国） | 韓 | Samsung 14nm/28nm/130nm、DB HiTek 180nm | 2026年から全面有料（例: 14nm 590万₩／3.55mm□） | NDA | 不要 | IDEC参加教授限定 |
| ミニマルファブ（横河ほか） | 日 | 0.5インチwafer、マスクレス露光 | 1個から試作受託、公開PDK・提出型サービスは未確認 | 個別 | 不要 | MPWではない代替 |

結論は次のとおりである。

- オープンPDK系（OpenSUSI、Tiny Tapeout、chipIgnite、IHP、wafer.space）の提出インタフェースは
  「テンプレrepo fork→`info.yaml`相当の宣言→GDS/netlist配置→GitHub Actionsでprecheck/DRC/LVS→
  repo URL提出→締切まで再提出」に収斂しており、ACDが生成する提出repoは1つの投影形式で
  複数提出先へ対応できる。
- 価格モデルは固定枠（OpenSUSI、chipIgnite、wafer.space）、tile課金（Tiny Tapeout）、
  面積課金（IHP、Europractice、CMC）の3種で、公開義務・地理制約・返却形態が提出先ごとに
  異なる。これらは提出先契約として宣言し、保存済み見積入力に無い値はunknownとして停止側へ
  集約する。
- DRC/LVS/MDPの実質標準はKLayout runsetであり、OpenSUSIとIHPはIIC-OSIC-TOOLSの構成に
  合わせている。ツールチェーンはADR-0047のdocker-only方針に従いdigest固定containerへ置く。
- NDA必須の商用・学術ブローカー（Europractice、MOSIS 2.0、Muse、CMC、VDEC、IDEC）は
  PDKを公開できず再現可能なゲートを組めないため、当面の対象外とする。
