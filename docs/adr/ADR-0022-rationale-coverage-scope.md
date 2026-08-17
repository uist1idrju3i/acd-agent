# ADR-0022: 設計根拠coverageの必須範囲と免除分類

> ステータス: Accepted
> 日付: 2026-08-17


## Context

部品、配置、配線幅、シルク、FWピン、機構寸法以外にも、stackup、
design rule、net class、安全境界、製造・populationの判断理由を保持する必要がある。
graph属性を追加する機能で記録漏れが起きないことも契約に含める。

## Decision

`acd_core.rationale`はgraphの属性を、設計者が選択した値を表す
`REQUIRED_RATIONALE_ATTRS`と、出典・標準定数・座標規約・識別子・一次資料の事実などを
明示的な英語理由付きで除外する`RATIONALE_EXEMPT_ATTRS`に分類する。どちらにもない属性は
`unclassified`としてcoverageをfail-closedにする。新しい設計判断を追加する変更は、同じ
変更で必須または免除の分類を追加し、必須ならrationale recordも追加する。

graphに要求nodeがある要求は`driving_requirements`で参照する。文書にしか存在しない要求は
`driving_requirement_refs`へ文書パスと要求IDを記録する。後者を無関係なgraph nodeで代用
してuntraceableを避けてはならない。

## Rationale

ピン番号、datasheet寸法、取得時刻、hashなどの一次資料・provenanceは、それ自体が設計者の
選択理由ではないため免除する。一方、製造条件、電気的限界、機械的余裕、配置探索規則など
設計者が採用した値は必須とする。未分類を明示的な失敗区分にすることで、将来の属性追加が
静かにcoverageの外へ逃げることを防ぐ。

## Consequences

coverage report、CLI、MCP、pipeline、Markdown投影は`unclassified`を公開する。未決の製造
事項や認証状態は決定済みとせず、recordの`assumptions`または`risks`に残す。
