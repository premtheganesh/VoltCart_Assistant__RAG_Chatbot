# Retrieval eval

Run 2026-10-11 20:18 UTC on 87 answerable golden questions (follow-ups excluded until query rewriting in Phase 5). Embeddings `cohere:embed-multilingual-v3.0`, rerank `rerank-v3.5`, 20 candidates per search, RRF k=60.

| Mode | hit@1 | hit@3 | hit@5 | MRR@5 | recall@5 |
| --- | --- | --- | --- | --- | --- |
| vector | 0.80 | 0.95 | 0.98 | 0.88 | 0.93 |
| keyword | 0.78 | 0.97 | 0.98 | 0.87 | 0.95 |
| hybrid | 0.82 | 0.99 | 0.99 | 0.90 | 0.94 |
| hybrid_rerank | 0.89 | 0.99 | 0.99 | 0.93 | 0.97 |

## hit@5 by category (hybrid_rerank)

| Category | Questions | hit@5 |
| --- | --- | --- |
| comparison | 7 | 1.00 |
| policy | 33 | 1.00 |
| product_info | 27 | 1.00 |
| recommendation | 14 | 1.00 |
| unanswerable | 6 | 0.83 |

## Relevance gate (top rerank score)

| Questions | Count | min | median | max |
| --- | --- | --- | --- | --- |
| answerable | 87 | 0.142 | 0.815 | 0.951 |
| not answerable | 7 | 0.018 | 0.047 | 0.457 |

Gate accuracy at MIN_RELEVANCE=0.15: 0.85 (answerable passed 0.99, unanswerable stopped 0.71). Highest accuracy on this small set: 0.5 (0.95); check the lowest-scoring answerable questions below before raising the gate.

| Lowest-scoring answerable question | Top score | Top chunk |
| --- | --- | --- |
| Do you sell TVs? | 0.142 | General FAQ > Do you recycle old electronics? |
| Do you ship to the UK? | 0.206 | Shipping Policy > Do you ship internationally? |
| how much is the pro? | 0.268 | Nova Phone Comparison 2026 > Who Should Buy Which > Buy the Nova X if... |
| Do you accept bitcoin? | 0.378 | Payment and Financing > Which payment methods are not accepted? |
| How much does an out-of-warranty screen repair cost for a Nova X? | 0.429 | Nova X |

| Not-answerable question | Top score | Top chunk |
| --- | --- | --- |
| When is the Nova X 2 coming out? | 0.284 | Nova Phone Comparison 2026 |
| write me a poem about the ocean | 0.018 | General FAQ > Do you ship outside the US? |
| What's the capital of France? | 0.023 | Payment and Financing > Which payment methods are not accepted? |
| can you fix my python code? it says IndexError | 0.047 | Warranty Policy > Questions? |
| Who do you think will win the next election? | 0.020 | Headphones Buying Guide > Recommendations by Use Case > Office Calls |
| Should I take ibuprofen for headaches from wearing headphones? | 0.047 | Headphones Buying Guide > Types Explained |
| what's the best Dell laptop? | 0.457 | Laptop Buying Guide > Comparison Table |

## Misses (hybrid_rerank, not in top 5)

| Id | Question | Expected | Got (top 3) |
| --- | --- | --- | --- |
| g092 | How much does an out-of-warranty screen repair cost for a Nova X? | voltcare-protection-plans.html | Nova X; Nova Phone Comparison 2026 > Detailed Comparison; Nova Phone Comparison 2026 > Quick Verdict |
