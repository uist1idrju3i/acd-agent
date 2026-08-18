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

agent-server系能力は保留（着手判断未決）とする。agent-serverをACDの実行契約として採用する
設計判断と、対象APIが認証・権限・Evidence境界を満たす受入試験を完了したことを着手条件とする。
現行のauthoritative実行経路は`DockerDevWorkspace`であり、`DockerWorkspace`やserver routerを
この判断なしに置き換えない。

## 採用範囲と権限境界

`sdk.llm.router`、`sdk.observability`、`sdk.logger`、`sdk.io`、`sdk.context.prompts`、
`sdk.context.view`、`sdk.context.memory`、`sdk.profiles`、`sdk.settings`、
`sdk.credential`は採用方針とするが、未実装の項目はカタログに「文書上の方針のみ、実装未着手」と
明記する。prompt、profile、settings資材はhashを記録し、unknownはfail-closedとする。

これらの能力、browser_use、agent-server、Skills、critic、agent、event、metrics、telemetryは
L2/L3に限定し、Evidence生成・昇格の権限を持たない。L1のpass authorityは従来どおり決定論的
gateとrevision一致したauthoritative Evidenceだけが担う。
