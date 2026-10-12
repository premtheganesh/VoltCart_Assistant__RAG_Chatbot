# Retrieval eval

Run 2026-10-12 19:13 UTC on 87 answerable golden questions (follow-ups excluded until query rewriting in Phase 5). Embeddings `cohere:embed-multilingual-v3.0`, rerank `rerank-multilingual-v3.0`, 20 candidates per search, RRF k=60.

| Mode | hit@1 | hit@3 | hit@5 | MRR@5 | recall@5 |
| --- | --- | --- | --- | --- | --- |
| hybrid_rerank | 0.89 | 0.99 | 0.99 | 0.93 | 0.96 |

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
| answerable | 87 | 0.004 | 0.994 | 1.000 |
| not answerable | 7 | 0.000 | 0.000 | 0.080 |

Gate accuracy at MIN_RELEVANCE=0.15: 0.98 (answerable passed 0.95, unanswerable stopped 1.00). Highest accuracy on this small set: 0.1 (0.99); check the lowest-scoring answerable questions below before raising the gate.

| Lowest-scoring answerable question | Top score | Top chunk |
| --- | --- | --- |
| Do you sell TVs? | 0.004 | General FAQ > Do you match prices? |
| Do you ship to the UK? | 0.009 | Shipping Policy > Do you ship internationally? |
| so my daughter starts college next fall and she's doing film, she needs something to edit videos from her camera, budget maybe around $1500, and she wants something she can actually carry around campus. what do you suggest? | 0.116 | VoltBook Pro 16 User Guide > Using features > 4K video editing workflow |
| My Air 14 battery health is at 85% after 10 months. Can I get it replaced under warranty? | 0.118 | VoltBook Air 14 User Guide > Battery and charging |
| I opened my Nova X but changed my mind. If I return it, how much do I get back? | 0.321 | Nova Phone Comparison 2026 > Trade-In and Financing > VoltPay Financing |

| Not-answerable question | Top score | Top chunk |
| --- | --- | --- |
| When is the Nova X 2 coming out? | 0.053 | Nova X Quick Start Guide > Overview |
| write me a poem about the ocean | 0.000 | Shipping Policy > What shipping methods are available? |
| What's the capital of France? | 0.000 | Account and Privacy FAQ > How do I update my shipping address on an order? |
| can you fix my python code? it says IndexError | 0.000 | Contact and Support Hours > How do I escalate an issue? |
| Who do you think will win the next election? | 0.000 | Headphones Buying Guide > Recommendations by Use Case > Office Calls |
| Should I take ibuprofen for headaches from wearing headphones? | 0.000 | Pulse ANC Headphones Manual > Care and safety |
| what's the best Dell laptop? | 0.080 | Laptop Buying Guide > Recommendations by Use Case > College Student or Tight Budget |

## Misses (hybrid_rerank, not in top 5)

| Id | Question | Expected | Got (top 3) |
| --- | --- | --- | --- |
| g092 | How much does an out-of-warranty screen repair cost for a Nova X? | voltcare-protection-plans.html | Nova Phone Comparison 2026 > Quick Verdict; Nova X; Nova X Pro |
