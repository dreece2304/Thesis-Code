# Weather backtest (2025-10-02 to 2026-09-13)

predictions: 10400, city-days: 1040, trade candidates: 1035, filled: 1033 (100%)

| scope | n | Brier ours | Brier market | Brier baseline | gap (mkt-ours) | 90% CI |
|---|---:|---:|---:|---:|---:|---|
| pooled | 10400 | 0.1641 | 0.1821 | 0.1795 | +0.0181 | [+0.0163, +0.0198] |
| CHI | 3470 | 0.1873 | 0.1882 | 0.1846 | +0.0009 | [-0.0024, +0.0039] |
| MIA | 3460 | 0.1363 | 0.1685 | 0.1661 | +0.0323 | [+0.0297, +0.0347] |
| NYC | 3470 | 0.1686 | 0.1896 | 0.1877 | +0.0211 | [+0.0181, +0.0241] |

P&L after fees: $51856.87 on $2000 (+2592.8%), max drawdown 36.7%, fees $4070.82
gate: PASS (ok)
