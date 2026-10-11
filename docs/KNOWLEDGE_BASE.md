# Knowledge Base — Documents the Chatbot Will Answer From

**Company (fictional):** VoltCart, an online consumer-electronics store selling laptops, headphones, phones and smart-home devices.

The knowledge base deliberately mixes **formats** (PDF, DOCX, HTML) and **content shapes** (prose, spec tables, troubleshooting tables, policies) so we exercise every part of the ingestion pipeline. Each document is first written as Markdown source in `sample_data/source/`, then rendered by a script into its final format in `sample_data/docs/` — so the chatbot ingests real PDF/DOCX/HTML files, exactly as it would in production.

## A. Product manuals and guides (PDF) — 8 files

| # | File | Contents | Example questions it answers |
|---|---|---|---|
| 1 | `voltbook-air-14-user-guide.pdf` | Thin-and-light laptop: spec table, battery tips, ports, setup, care | "How long does the VoltBook Air battery last?" |
| 2 | `voltbook-pro-16-user-guide.pdf` | Creator laptop: CPU/GPU options table, display calibration, thermals | "Is the Pro 16 good for 4K video editing?" |
| 3 | `voltbook-gamer-15-user-guide.pdf` | Gaming laptop: GPU, refresh rate, cooling modes, RGB | "What refresh rate does the Gamer 15 screen have?" |
| 4 | `pulse-anc-headphones-manual.pdf` | Over-ear ANC headphones: modes, pairing, app, troubleshooting table | "How do I pair Pulse ANC with two devices?" |
| 5 | `stride-sport-earbuds-manual.pdf` | Sports earbuds: IP rating, fit, controls, battery case | "Can I swim with Stride earbuds?" |
| 6 | `nova-x-phone-quick-start.pdf` | Smartphone: setup, camera modes, charging, SIM/eSIM | "Does the Nova X support eSIM?" |
| 7 | `homehub-speaker-setup.pdf` | Smart speaker/hub: setup, voice assistants, Matter support | "Does HomeHub work with Google Home?" |
| 8 | `glowbulb-and-smartplug-guide.pdf` | Smart bulb + plug: pairing, Wi-Fi requirements, reset table | "My GlowBulb won't connect, what do I do?" |

## B. Buying guides and comparisons (DOCX) — 4 files

| # | File | Contents | Example questions |
|---|---|---|---|
| 9 | `laptop-buying-guide.docx` | Which laptop for students, gaming, video editing, business; comparison table | "Best laptop for a college student under $900?" |
| 10 | `headphones-buying-guide.docx` | ANC vs open, wired vs wireless, running vs commuting | "Which headphones are best for running?" |
| 11 | `phone-comparison-2026.docx` | Nova lineup comparison table: camera, battery, price | "Nova X vs Nova Lite camera?" |
| 12 | `smart-home-starter-guide.docx` | Starter bundles, compatibility matrix (Alexa / Google / Apple / Matter) | "What do I need to start a smart home?" |

## C. Help-center pages (HTML) — 9 files

| # | File | Contents | Example questions |
|---|---|---|---|
| 13 | `shipping-policy.html` | Shipping methods, times, costs, international | "How long does express shipping take?" |
| 14 | `returns-and-refunds.html` | 30-day window, condition rules, opened items, refund timing | "Can I return opened headphones?" |
| 15 | `warranty-policy.html` | 1-year limited warranty, what's covered, claim steps | "Is water damage covered?" |
| 16 | `voltcare-protection-plans.html` | Extended plans: tiers, prices, accidental damage | "What does VoltCare Plus cover?" |
| 17 | `payment-and-financing.html` | Cards, PayPal, 0% financing terms, gift cards | "Can I pay in installments?" |
| 18 | `order-tracking-help.html` | Order statuses explained, changing/cancelling orders | "What does 'processing' mean?" |
| 19 | `account-and-privacy-faq.html` | Accounts, data, deleting data, newsletters | "How do I delete my account?" |
| 20 | `contact-and-support-hours.html` | Support channels, hours, escalation | "When is support open?" |
| 21 | `general-faq.html` | Price match, student discount, store pickup, trade-in | "Do you offer a student discount?" |

## D. Structured data (Postgres tables — accessed through tools, NOT embedded)

| Data | Rows (approx.) | Used for |
|---|---|---|
| `products` (name, category, price, specs JSON, stock, rating, short description) | 20 SKUs (4–6 per category) | Product search, filtering ("under $150"), comparison. Product descriptions ARE also embedded for semantic search. |
| `customers` | 12 | Order verification (email must match) |
| `orders` + `order_items` | 30 | Order status lookup after verification |
| `shipments` | 25 | Carrier, tracking number, estimated delivery |

## E. Test-only documents (used in later phases)

| File | Purpose |
|---|---|
| `returns-and-refunds-v2.html` | An updated policy (45-day window) to test that re-indexing replaces old content |
| Off-topic / injection prompts | Live in `evals/datasets/guardrails.jsonl`, not in the knowledge base |

**Total:** 21 knowledge documents + 4 tables. Small enough to inspect by hand, rich enough to test tables, multi-format parsing, policies, product recommendations and order lookups.
