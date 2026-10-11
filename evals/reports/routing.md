# Routing eval

Run 2026-10-11 23:08 UTC, router `groq:qwen/qwen3.8-27b`, 109 golden questions.

**Accuracy: 0.98** (target 0.9)

| Expected route | Questions | Correct |
| --- | --- | --- |
| handoff | 2 | 2 |
| off_topic | 1 | 1 |
| order | 13 | 13 |
| product_info | 70 | 68 |
| recommendation | 22 | 22 |
| smalltalk | 1 | 1 |

## Wrong routes

| Id | Question | Expected | Got |
| --- | --- | --- | --- |
| g010 | turbo mode is greyed out on my gaming laptop | product_info | off_topic |
| g067 | My tracking says delivered but there's no package | product_info | order |

## Follow-up rewrites

| Id | Question | Rewritten search query |
| --- | --- | --- |
| g082 | how much is it and does it take a memory card? | Nova X price and memory card support |
| g083 | ok and what would the protection plan with accident cover cost for it? | VoltCare protection plan with accident cover cost for Pulse ANC |
| g084 | is there something cheaper that still works for that? | cheaper VoltBook laptop for 4K video editing |
| g085 | btw unrelated but how long do refunds usually take? | how long do refunds usually take? |
| g095 | sofia.ramirez@example.com | Where's order VC-10003? |
| g100 | ok can I still cancel it? | Can I still cancel order VC-10017? |
| g101 | actually I want to cancel it | cancel order VC-10003 |
