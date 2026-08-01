# Presentation Script — Autonomous Company Research Agent

Format: ~3 minutes talking with slides, ~2 minutes live demo, ~5 minutes total.
Tone: confident, conversational, not a technical lecture. Speak the ideas — don't read the slides verbatim.

---

## Talking Track (~3:15)

### Slide 1 — Title — 15s
"Hi, I'm Carlos Felipe Valencia, and this is my Project 3 for Ironhack's AI Consulting & Integration program: an Autonomous Company Research Agent — a pipeline that turns SEC filings into structured business intelligence."

*Transition:* "Before I get into the project, a quick word about me."

### Slide 2 — About Me — 20s
"I'm Colombian, based in Mallorca, Spain. My background is in marketing, branding, and UX — I've spent years helping companies with digital strategy and customer experience. Right now I'm transitioning into AI consulting, because I want to connect that business intuition with systems that actually work."

*Transition:* "So why company research, specifically?"

### Slide 3 — Elevator Pitch — 25s
"Because right now, company research is manual. Analysts dig through filings, financial data, and news across a dozen disconnected tools, and it's hard to trace any single fact back to its source. This project automates that: it's an autonomous research pipeline that turns authoritative company data into structured, source-grounded evidence — ready for business analysis and automation."

*Transition:* "Let me show you how that actually works end to end."

### Slide 4 — How It Works — 35s
"It starts with a business question, submitted through the CLI or n8n. LangGraph orchestrates the whole flow. On the ingestion side, it resolves the company, pulls filings straight from SEC EDGAR, normalizes and chunks the text, embeds it with OpenAI, and indexes it in Pinecone. On the query side, it runs semantic retrieval and assembles that into traceable evidence. And on the output side, it emits deterministic JSON that a self-hosted n8n workflow can pick up to drive an executive report. Each of those services has one job, and it's independently tested."

*Transition:* "Building that contract-driven pipeline is where the real difficulty showed up."

### Slide 5 — Technical Challenge — 30s
"The hardest part wasn't calling an API — it was keeping every chunk's identity intact all the way through the pipeline. At one point, a string-normalization step was silently rewriting a chunk's text ID before it reached Pinecone, which broke the vector-preparation contract downstream. The fix was narrow: preserve that identifier exactly, while keeping every other metadata check in place. It's a small thing, but it taught me how easily a small metadata change can break an entire RAG pipeline."

*Transition:* "That wasn't the only lesson."

### Slide 6 — Biggest Mistake — 25s
"My biggest mistake was sequencing. I designed and tested every layer in isolation before validating a full live path with real providers — which meant I discovered environment and integration issues later than I should have. If I did it again, I'd connect one real provider, validate one complete vertical slice end to end, and only then expand. Architecture matters, but the first working vertical slice matters more."

*Transition:* "So where does that leave the project today?"

### Slide 7 — Results — 25s
"The core pipeline is real, not theoretical. I ingested one Apple 10-K end to end: 245 chunks, 245 vectors indexed, all 245 accepted by Pinecone. And the full test suite — 500 automated tests — passes offline, with providers mocked. What's still in progress is stabilizing live provider execution in my Windows environment, validating live retrieval end to end, and finishing the visual n8n workflow and executive report output."

*Transition:* "Let's see it."

### Slide 8 — Demo transition — 10s
"Here's DEMO — let me walk you through the pipeline live."

### Slide 9 — Closing — 10s
"That's the Autonomous Company Research Agent. I'm Carlos Felipe Valencia — thank you."

---

## Live Demo Plan (~2:00)

**Primary demo** — use if live provider connectivity is working:

| Time | Action | What to click / show |
|---|---|---|
| 0:00–0:20 | Open Pinecone console | Show the index and its 245 stored records for the Apple namespace. |
| 0:20–0:35 | Narrate the ingestion | Explain that Apple's 10-K produced 245 chunks, embedded and indexed as 245 vectors — say the numbers, don't type the command on screen. |
| 0:35–1:15 | Execute the workflow | Run the n8n runner with the explicit canonical-company override (`--resolved-ticker AAPL --resolved-cik 0000320193`) from a terminal already positioned and ready — don't narrate the flags, just say "I'm giving it Apple's known identity so it skips the SEC lookup and goes straight to retrieval." |
| 1:15–1:40 | Show the LangGraph flow | Point at the architecture slide (Slide 4) or a terminal trace showing `resolve_company → validate_company → retrieve_research → assemble_evidence → complete_workflow`. |
| 1:40–2:00 | Show the output | Show the structured JSON printed to stdout — evidence records, company identity, workflow status — and mention the n8n handoff if the workflow is wired up. |

**Backup demo** — use if live provider transport is unstable (a known, isolated Windows-environment issue, not an architecture defect):

1. Show the Pinecone console screenshot / dashboard with the 245 indexed records — this is verified ingestion, already completed.
2. Walk through the architecture slide (Slide 4) instead of a live trace.
3. Show the test suite passing (500 tests) as evidence the workflow logic is validated, even where live transport is not being demoed.
4. Be explicit with the audience: *"This shows the verified ingestion and tested architecture — I'm not going to fake a live retrieval run that didn't happen."*

No fabricated evidence JSON is used in either path — the repository does not currently contain a saved end-to-end evidence output, and none is presented as if it were live.

---

## Notes

- Keep the terminal font large and the window pre-positioned before you start talking.
- Do not read command flags aloud — say what they *do*, not what they *are*.
- If a live call fails mid-demo, don't troubleshoot on stage — say "this is the known environment issue I mentioned" and switch straight to the backup steps above.
