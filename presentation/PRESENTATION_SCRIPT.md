# Presentation Script — Autonomous Company Research Agent

Format: 9 slides, ~6:15 talking with slides, ~3:00 live demo, ~9:15–10:00 total.
Tone: confident, conversational, not a technical lecture. Speak the ideas — don't read the slides verbatim.

---

## Talking Track (~6:15)

### Slide 1 — Title — 0:20
"Hi, I'm Carlos Felipe Valencia, and this is my Project 3 for Ironhack's AI Consulting & Integration program: an Autonomous Company Research Agent — a pipeline that turns SEC filings into structured business intelligence."

*Transition:* "Before I get into the project, a quick word about me."

### Slide 2 — About Me — 0:40
"I'm Colombian, based in Mallorca, Spain. My background is in marketing and advertising — I've spent years on business strategy, UX, branding, and digital transformation. Right now I'm focused on AI consulting and integration. And outside of work, I'm a rescue diver and underwater sports enthusiast."

*Transition:* "So why company research, specifically?"

### Slide 3 — Project Elevator Pitch — 0:55
"Business analysts spend hours reading long SEC filings, and the evidence they need is scattered and hard to trace. The Autonomous Company Research Agent retrieves company-specific evidence from authoritative SEC filings and returns structured, source-grounded results. I chose this project because it combines business research, AI orchestration, RAG, and automation into one practical consulting use case. Instead of replacing the analyst, the system accelerates the evidence-gathering process."

*Transition:* "Let me show you how that actually works."

### Slide 4 — How It Works — 1:05
"It starts with a business question. n8n and LangGraph orchestrate the workflow. From there it pulls authoritative filings from SEC EDGAR and runs semantic search with OpenAI embeddings and Pinecone. That evidence gets assembled and returned as a structured result with traceable SEC source URLs — all behind an authenticated FastAPI endpoint deployed on Railway."

*Transition:* "Building that pipeline is where the real difficulty showed up."

### Slide 5 — Technical Challenge — 1:10
"The most important technical challenge: Microsoft retrieval was failing in production even though every provider was returning HTTP 200. The cause was a metadata mismatch — Pinecone had the company stored as 'MICROSOFT CORP,' while company resolution returned 'Microsoft Corporation.' My normalization layer treated those as two different companies and rejected every match. The fix was alias-aware, legal-suffix normalization, while still strictly rejecting genuinely different companies. Microsoft retrieval was restored, I added regression tests, and the full suite of 550 tests stayed green."

*Transition:* "That wasn't just a bug — it taught me something bigger about how I was validating this project."

### Slide 6 — Biggest Mistake — 1:05
"My biggest mistake was validating individual components before validating the complete production path. OpenAI returned 200. Pinecone returned 200. The workflow completed. But the final evidence bundle was empty, because metadata and normalization contracts were inconsistent between them. Successful provider calls don't prove the full workflow works — the lesson is to validate the user-visible result end-to-end as early as possible."

*Transition:* "So where does that leave the project today?"

### Slide 7 — Final Results — 0:45
"This is a deployed and fully tested project pipeline: 550 automated tests passing, Apple and Microsoft evidence retrieval both verified, an active Railway production deployment, and a completed n8n workflow. SEC ingestion, RAG retrieval, the authenticated API, source-grounded evidence, and documentation are all in place."

*Transition:* "Let's see it."

### Slide 8 — Demo transition — 10s
"Here's DEMO — let me walk you through it live."

### Slide 9 — Closing — 0:15
"That's the Autonomous Company Research Agent — accelerating company research with authoritative, traceable evidence. I'm Carlos Felipe Valencia. Thank you."

---

## Live Demo Plan (~3:00)

The presentation itself stops on the DEMO slide. Run the live demo separately, then return to the Closing slide.

| Time | Action | What to show |
|---|---|---|
| 0:00–0:30 | Open n8n | Show the workflow canvas at a high level — trigger, validation, API call, presentation branch. Don't narrate every node. |
| 0:30–1:15 | Run the Apple request | Trigger the manual demo run (or the webhook) for Apple Inc. |
| 1:15–2:00 | Open the final Research Result | Show `status: completed`, the resolved company, evidence count, evidence text, similarity score, and the SEC source URL. |
| 2:00–2:40 | Run or show the Microsoft request | Confirm it now returns evidence successfully. |
| 2:40–3:00 | Explain the regression case | Briefly note this is the exact bug fixed on Slide 5 — say what changed, don't re-read the slide. |

Then return to the Closing slide for the final line and questions.

**Backup demo** — use if live provider transport is unstable:

1. Show a screenshot of the n8n workflow canvas and a prior successful Apple execution.
2. Walk through the How It Works slide (Slide 4) instead of a live trace.
3. Be explicit with the audience: *"This shows verified, tested behavior — I'm not going to fake a live run that didn't happen."*

No fabricated evidence JSON is used in either path.

---

## Notes

- Keep the terminal/browser window large and pre-positioned before you start talking.
- Say what commands and nodes *do*, not what they *are*.
- If a live call fails mid-demo, don't troubleshoot on stage — say "this is a known environment issue" and switch to the backup steps above.
- Before presenting, replace `N8N_WORKFLOW_URL` in `index.html` with the local n8n workflow URL (see `DEPLOYMENT.md`).
