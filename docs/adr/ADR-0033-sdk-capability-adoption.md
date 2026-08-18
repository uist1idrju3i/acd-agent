# ADR-0033: SDK能力の採否とbrowser_useの境界

- ステータス: Accepted
- 対象: OpenHands Software Agent SDK v1.42.1

## 決定

`browser_use`はLLM駆動のbrowser操作toolsetであり、決定論的なHTTP取得APIではない。
そのため、LCSCのEasyEDA API取得経路は変更せず、browser_useは決定論的APIがない部品調査や
datasheet確認のL2探索補助に限定する。browser由来の観測をEvidenceへ昇格させず、設計入力へ
確定する場合は既存の決定論的経路で再取得し、入力hashを記録する。

ACDのconversationではbrowser toolを既定無効とし、明示的に有効化した場合だけChromiumの
利用可能性を検査して登録する。明示有効時に利用不能なら例外で停止し、黙って無効化しない。

`sdk.tools.workflow`は不採用（将来再検討）とする。LLMが作成した任意Python scriptを実行し、
script自体がhook matcherの外側になるため、ACDのfail-closed境界を貫通しうるためである。
map/reduceやlaneの意味的mergeは既存の決定論的入口とSDKの安全なtask境界で扱う。

agent-server系能力はACDの対象外とする。agent-serverをACDの実行契約として採用する場合は、
認証・権限・Evidence境界を満たす受入条件を定義した新規ADRを起票する。
authoritative実行経路は`DockerWorkspace(server_image=...)`である。6.3〜6.5で
SDKのdev workspace経路（on-the-fly build）からの移行を完了した。server routerの採用は
この判断なしに行わない。

## 採用範囲と権限境界

`sdk.llm.router`、`sdk.observability`、`sdk.logger`、`sdk.io`、`sdk.context.prompts`、
`sdk.context.view`、`sdk.context.memory`、`sdk.profiles`、`sdk.settings`、
`sdk.credential`は採用方針とするが、未実装の項目はカタログに「文書上の方針のみ、実装未着手」と
明記する。prompt、profile、settings資材はhashを記録し、unknownはfail-closedとする。

これらの能力、browser_use、agent-server、Skills、critic、agent、event、metrics、telemetryは
L2/L3に限定し、Evidence生成・昇格の権限を持たない。L1のpass authorityは従来どおり決定論的
gateとrevision一致したauthoritative Evidenceだけが担う。
