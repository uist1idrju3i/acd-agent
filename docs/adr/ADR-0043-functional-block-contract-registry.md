# ADR-0043: 機能ブロック契約registryによる設計述語の適用条件

> ステータス: Accepted
> 日付: 2026-08-23
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`../operations.md`](../operations.md)

## コンテキスト

従来の設計述語はGD1のnet名、部品、電源構成を常に要求していた。そのためUSB-Cや
I2Cを持たない正当なトポロジも、存在しないnetを`unknown`として不合格になった。
一方、適用対象なのに入力が欠けている状態は検証不能であり、合格へ迂回させてはならない。

また、製造 profileが単一パスに固定されており、graphが宣言する製造条件と選択可能な
profileの対応を追跡できなかった。

## 決定

1. graphの`design.functional_block`ノードで、要件を駆動する機能ブロックを宣言する。
   ノードの属性はregistryの`block_id`だけとし、`depends_on`で駆動requirementを参照する。
2. `contracts/functional-block-registry.json`を契約の正とし、各機能ブロックが必須とする
   設計述語を宣言する。registryと述語catalogの被覆は相互に完全でなければならない。
3. 宣言されたブロックに対応する述語だけを評価し、それ以外は`not_applicable`とする。
   宣言されたブロックの入力不足は従来どおり`unknown`としてfail-closedにする。
   宣言ゼロ、未知ID、mandatoryブロック欠落も停止する。
4. Evidenceにはregistry ID・正規化hashと宣言ブロック一覧を記録し、
   `not_applicable`の述語claimは記録しない。visual projectionには適用述語だけを渡す。
5. `profiles/fab-profile-registry.json`でprofile IDとパス、fab、processの対応を管理する。
   CLIの明示パス、profile ID、graph宣言の順で選択し、registry metadataとprofile本体を
  照合する。

## 却下した代替案

- netや部品の存在から適用条件を推測する案は、未宣言を適用外としてしまい、設計意図と
  検証不能を区別できないため却下した。
- `unknown`を`not_applicable`へ変換する案は、fail-closed境界を緩めるため却下した。
- 述語側へトポロジごとの分岐を追加する案は、GD1固定とコード変更の結合を残すため却下した。
- 2件目のfab capability値を推測して追加する案は、出所のない製造条件を作るため却下した。

## 影響範囲

GD1は6機能ブロックを宣言し、従来の6述語をすべて適用する。別トポロジは必要な
機能ブロックだけを宣言できるが、安全電源境界は必須である。registryの不整合、
宣言の不備、profileの不一致はすべて停止側へ倒れる。述語のnet名、閾値、判定ロジック、
L1権限、authoritative Evidenceの条件は変更しない。
