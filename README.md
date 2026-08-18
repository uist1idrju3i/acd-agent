# ACD — Autonomous Computer Design

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/uist1idrju3i/acd-agent)

ACDは、基板・筐体・ファームウェアをOpenHandsと決定論的な投影・ゲートで扱う
AIファーストCADです。AIとSkillは候補を提案し、ERC/DRC、独立再読込、機械測定などの
決定論的ゲートが合否を判定します。

## ACDとは？

ACDは従来のEDA/MCADのモデルを反転させ、AIが主たる設計者となることを目指します。AIは
要件のヒアリング、部品選定、回路・基板レイアウト・筐体・ファームウェアの設計、製造データの
生成、製造・実機フィードバックを受けた反復までを担い、人間は要件のオーナーとして関わり、
必要に応じてレビュアーの役割も担えます。ACDという名称はCADのアナグラムとして、人間主体から
AI主体への役割反転を象徴します。

対象は趣味・研究・小規模試作です。1〜4層リジッド基板と、3Dプリント・卓上切削・簡易CNCで
製造できる筐体を扱い、高密度多層・フレキシブル・認証が必要な量産設計は将来の拡張領域です。
現行の対象範囲と最小構成の方針は
[`docs/adr/ADR-0008-minimal-vibebb-scope.md`](docs/adr/ADR-0008-minimal-vibebb-scope.md)を正とします。

本リポジトリはOpenHands専用拡張です。境界と不採用機能は
[`docs/adr/ADR-0026-openhands-delegation-contract.md`](docs/adr/ADR-0026-openhands-delegation-contract.md)、
SDKの採否は[`docs/openhands-sdk-capabilities.json`](docs/openhands-sdk-capabilities.json)を正とし、
説明表は[`docs/openhands-sdk-capabilities.md`](docs/openhands-sdk-capabilities.md)で確認できます。
文書統治は[`docs/adr/ADR-0034-document-governance.md`](docs/adr/ADR-0034-document-governance.md)に従い、
agent-serverは対象外です。

## VibeBB — Vibe BreadBoarding

VibeBBは、Vibe Codingになぞらえた「Vibe BreadBoarding」です。Andrej Karpathyが
[2025年2月の投稿](https://x.com/karpathy/status/1886192184808149383)で示した
「完全にバイブスに身を委ね、コードの存在すら忘れる（fully give in to the vibes,
embrace exponentials, and forget that the code even exists）」という発想と、
「see stuff, say stuff, run stuff」の対話的なループを、基板・筐体・FWの試作と検証へ持ち込みます。
[Collins英語辞典の2025年Word of the Year](https://blog.collinsdictionary.com/language-lovers/collins-word-of-the-year-2025-ai-meets-authenticity-as-society-shifts/)
が示すように、自然言語で目的を伝え、結果を見て、次の指示を返す開発体験は広がっています。

ブレッドボード（BreadBoard）がハンダ付けなしに「考えながら試す」ことを可能にしたように、
VibeBBではやりたいことを言葉で伝えるだけで、AIが部品選定、回路、基板レイアウト、筐体、
ファームウェア、製造データを進め、人間は動く試作基板と収まる筐体を見てフィードバックを返します。
回路図を描かないことは、コードを読まないVibe Codingと対になる発想です。

VibeBBは、設計や検証が軽いという意味ではなく、重い検証を人間の手作業から隠すという意味です。
[Simon Willison](https://simonwillison.net/2025/Mar/19/vibe-coding/)が区別した
生成物をレビューしない本来のVibe Codingとレビューを伴うAI活用を踏まえ、ACDはレビューの
役割を人間から決定論的ゲートと実機Evidenceへ移します。人間レビューは任意であり、合否権限を
持ちません。ツール不在、parse失敗、ゲート未実行、unknownはfail-closedとします。

流れは、**語る（要件を伝える）→ AIが設計し決定論的ゲートで検証する → 作って試す
（製造・実機テスト）→ 測定結果を次の設計へ返す**です。長時間の机上検討よりも、まず作って
実機で確かめ、すぐ次の変更を回すことを基本サイクルにします。

## 製品ビジョン

ACDは、要件から基板・筐体・ファームウェアを設計し、製造データを生成し、検証結果を
次の設計入力へ戻す最小の縦断を目指します。人間は要件のオーナーとフィードバックの提供者に
集中し、OpenHandsが対話、Skill、subagentを使って候補と修正案を整理します。合否は常に
決定論的ゲートが担い、authoritative Evidenceはdigest固定container実行だけが生成します。

設計は次の3レーンを同じ入力ファイルとgitの履歴から扱います。

- **基板レーン**: 部品、回路意図、配置・配線、ERC/DRC、製造出力。
- **筐体レーン**: 外形、部品高さ、締結、干渉、clearance、肉厚、CAD出力。
- **FWレーン**: OpenHandsへ委譲する実装、ビルド、静的検査、仮想実行。

価格・在庫・納期取得、発注、量産対応は将来範囲です。現在の実装状況はこの節ではなく
[`docs/roadmap.md`](docs/roadmap.md)を正とします。

## インストール

OpenHandsのLocal GUI（Agent Canvas）の「カスタマイズ → Plugins →
プラグインを追加」から、ソース`github:uist1idrju3i/acd-agent`、パス`plugins/acd`で
インストールできます。
パスは必須で、省略するとACDのSkill／AgentDefinition／command／hooksは読み込まれません。

通常の最新化（default branchの先頭への更新）は、同じPlugins画面の「更新」ボタンだけで
行えます。アンインストールは不要で、有効・無効の状態も維持されます。特定のtagまたは
40桁commit SHAへ固定・切替・ダウングレードする場合は、更新ボタンでrefを指定できないため、
いったんアンインストールして新しいrefで再インストールします。

その他の運用手順は[`docs/operations.md`](docs/operations.md)を参照してください。

## 文書索引

文書の一覧とAccepted ADRの索引は[`docs/README.md`](docs/README.md)を参照してください。
