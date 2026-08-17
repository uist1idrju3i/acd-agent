# ADR-0017: 決定論的探索並列化と探索lane

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

GD1基板pipelineのKiCad width positive-control armだけをACD側で並列化する。
arm-a（class-only）とarm-b（class-and-board-minimum）は別ディレクトリで別の
KiCad DRC subprocessを実行するため独立している。thread poolを使い、既定の
並列度は2、`1`を指定した場合は従来どおり逐次実行する。

結果はarm-a、arm-bの固定順で集約する。workerの例外は抑制せずpipelineの既存の
fail-closed経路へ伝播させ、部分結果を成功扱いしない。worker数1と4で、出力パスと
KiCad DRC日時を除いたarm summaryの正規化比較がbyte一致することを検証した。

`hashes.json`はworker数1と4でbyte一致しなかった。これは並列化が導入した差ではなく、
基板pipeline既存経路が実行ごとに生成するKiCad UUIDとDRC日時に由来する既存の
非決定性である。この非決定性の是正はP4の範囲外の未解決事項とする。

## workflow toolを採用しない理由

OpenHands SDK v1.42.1の`openhands.tools.workflow`は`run_agent`、
`map_agents`、`reduce_agent`、`pipeline`、`flatten`によるLLM subagentの
orchestrationである。workflow scriptはshell実行やファイル読み書きを行わない
契約なので、決定論的CLI探索を載せると外部ツール実行とprovenanceがACDの管理外に
なる。したがってworkflowは採用せず、決定論的探索の並列化はACD pipelineに置く。

## 探索laneの境界

`acd-search` AgentDefinitionは既存の探索CLIをterminal経由で実行し、候補とSkill名・
script SHA-256のprovenanceだけを返す。候補やagent出力は合否Evidenceではなく、
設計入力へ確定した後に既存の決定論的ゲートが判定する。greedyな配置探索と
silkscreen探索は前段の状態に依存するため、このADRでは並列化しない。
