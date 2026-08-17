# ADR-0029: Agent安全境界のSDK委譲

> ステータス: Accepted
>
> 日付: 2026-08-17

## コンテキスト

ACDのagent経路には、操作の確認、秘密の注入、Skill資材の配布、停滞検知が必要で
ある。一方、これらは設計契約や決定論的gateの合否を担う責務ではない。独自の
安全・秘密・Skill・停滞基盤を追加せず、pinned OpenHands SDK v1.42.1の機能を
L2として採用する。

## 決定

- 決定論的な`AcdSecurityAnalyzer`とSDK `PatternSecurityAnalyzer`を
  `EnsembleSecurityAnalyzer(analyzers=[...])`へ渡す。ensembleは例外をHIGHとして
  扱い、既定では`UNKNOWN`を除いた具体的riskの最大値を返し、全てUNKNOWNなら
  UNKNOWNを返す。`LLMSecurityAnalyzer`、`ToolShieldLLMSecurityAnalyzer`、
  `GraySwanAnalyzer`は採用しない。
- Conversationへ`set_security_analyzer()`と
  `set_confirmation_policy(ConfirmRisky(threshold=SecurityRisk.MEDIUM))`で設定する。
  HIGHとMEDIUMは確認し、LOWは通過させる。
- 明示allowlistの環境変数だけをlazy `SecretSource`として
  `LocalConversation(secrets=...)`に渡し、SDK
  `SecretRegistry.mask_secrets_in_output()`を出力maskingの権威とする。計画が想定した
  callableをSDKの`SecretValue`へ直接渡すことは、pinned実装の`_wrap_secret()`が
  `str | SecretSource`以外を拒否するため採用しなかった。ACDの`EnvironmentSecret`は
  `get_value()`を遅延実行する。secret値はログ、
  ToolEnvelope、Evidenceへ入れない。
- `load_skills_from_dir(skill_dir: str | Path)`で`plugins/acd/skills`だけを読み、
  `AgentContext(skills=...)`へ渡す。public/user/marketplace自動読み込みは無効にする。
  SDK loaderが個別エラーを警告して継続する事実に対しては、ACD wrapperが
  `Skill.load()`の事前検証とロード数照合を行い、壊れた資材をfail-closedにする。
- `LocalConversation(stuck_detection=True)`とSDK `StuckDetectionThresholds`を採用し、
  停止・修正の操舵に限定する。

## 権限境界

上記のanalyzer、confirmation policy、secret registry、Skill、stuck detectorは全て
L2である。停止や確認を要求できるが、Evidenceを生成せず、
`Evidence.supports_authoritative_pass()`の結果を変更しない。既存のorder guard、
projection保護、stop policy hookは最終的なagent経路境界として維持する。L1の合否は
digest固定containerで実行されたrevision一致の決定論的gateとauthoritative Evidenceだけが
担う。

## 影響

SDKの既存実装へ委譲し、ACD側の重複基盤を増やさない。ローカルSkillの破損は警告で
継続せず停止する。host実行は従来どおり参考実行として利用できるが、L2機能の有無に
関係なくprovisionalのままである。

## 検証

risk分類、ensemble最大severity、確認閾値、allowlistとmasking、壊れたSkillの拒否、
Conversation wiring、custom stuck thresholds、およびL2機能がauthoritative Evidenceを
生成・昇格できないことを回帰試験で固定する。
