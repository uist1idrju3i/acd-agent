# ADR-0031: lane並列とsub-agent境界

> ステータス: Accepted
>
> 日付: 2026-08-18

## コンテキスト

OpenHands SDK v1.42.1は、`Agent.tool_concurrency_limit`から
`ParallelToolExecutor`を構成し、`ToolDefinition.declared_resources()`の結果で
共有資源をロックする。資源宣言の既定値は`declared=False`であり、SDKはtool単位の
mutexへ倒して並列実行を直列化する。

SDKの`DelegateExecutor`はsub-agentを別`LocalConversation`として作成し、親のhookを
継承しない。確認方針は継承されるが、ACDの投影保護、order guard、gate要求は親だけに
依存してはならない。

## 決定

- ACDは`tool_concurrency_limit`の既定値1を維持し、2以上は呼び出し側の明示指定に限る。
- `acd_*` toolは入力graphと出力directoryを`DeclaredResources`へ明示する。
  path解決不能時は`declared=False`としてSDKの直列化へ倒す。
- 5つのACD AgentDefinitionへ、hooks.jsonの必須hookを明記する。
  検査はfrontmatter文字列ではなく`AgentDefinition.load()`後の`HookConfig`を対象にする。
- task/delegateはL2の実行・操舵経路として扱い、sub-agentの結果をEvidenceへ昇格しない。
- workflowの採否は、任意Python script実行の安全境界を含めて別途判断する。

## 権限境界

並列実行、task、delegateはEvidenceを生成・昇格しない。合否は決定論的gateと、
digest固定containerで実行されたrevision一致Evidenceだけが担う。hook drift、
資源宣言不能、path解決失敗はfail-closedとする。

## 影響

異なる資源を扱うtoolは明示的な資源keyの範囲で並列化できる。同一出力先や資源宣言不能
なtoolはSDKのmutexで直列化され、並列度によって入力・出力hashが変わることを防ぐ。
sub-agentにも必須hookが適用されるため、親hook非継承による安全境界の欠落を防止できる。

## 検証

5つのAgentDefinitionのHookConfig照合、hook driftのnegative test、ACD toolの資源key、
path解決失敗時の直列化、tool concurrency設定、同一出力先のmutex、workflow採否の境界、
sub-agentの非authoritative境界を回帰試験で固定する。
