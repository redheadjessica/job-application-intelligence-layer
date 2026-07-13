# Application Learning Ledger

Durable lessons from **completed, submitted** applications, produced by the reconcile workflow (`reconcile-spec.md`). Append-only, keyed by application folder.

## What this is

The long-term memory of the learning loop. Every entry records what the tailoring agent *recommended* for a given application versus what you *actually submitted*, plus any lessons inferred from the difference. It is the record layer — nothing here automatically edits a canonical generation file (see `reconcile-spec.md` §8). Concrete edit proposals live in `source-update-queue.md`.

## How entries get added (never by hand from a draft)

1. You submit an application and move its folder into your trusted submitted-applications archive.
2. You run the reconcile workflow on that folder (see `reconcile-spec.md`). It compares the agent's first-pass recommendation against the final submitted résumé.
3. Reconcile **appends a candidate entry here**, keyed by the application folder name (so re-running is idempotent — the same folder is never double-appended), marked `pending`.
4. After you answer the "why did you change X?" questions, a confirm pass promotes confirmed lessons to `confirmed`.

**Hard rules:**
- An entry is **never** written from an in-progress tailoring draft — only from a reconcile of a submitted application in the archive.
- This file is human-reviewed; nothing here auto-edits canonical files.
- It stores lessons and patterns only — **never** raw personal cover-letter or application-answer text.
- This is a maintenance/learning file. It is **not** read during a normal résumé-generation run.

---

## Patterns tracker (recurring lessons across applications)

A roll-up of lessons that recur across applications. When the same lesson shows up in a second application, increment its occurrence count and add the application here rather than creating a new row.

| Lesson (short) | Category | Occurrences | Applications | Status |
|---|---|---|---|---|
| Negative-qualifier boundary clauses in bullets read as over-hedged; positive framing alone is sufficient | voice | 1 | Thornbury Sr PMM AI Workflows 06-25-26 | watch — 1 occurrence; queue-ready on confirmation or 2nd occurrence |
| AI-capability boundary language lands better in summary/skills than as a bullet tail | voice | 1 | Thornbury Sr PMM AI Workflows 06-25-26 | watch — 1 occurrence; queue-ready on confirmation or 2nd occurrence |
| IC-only roles: suppress people-management bullets when the JD has no people-management scope | content | 1 | Thornbury Sr PMM AI Workflows 06-25-26 | watch — 1 occurrence; queue-ready on confirmation or 2nd occurrence |
| Skills inclusion mirrors JD presence; skills absent from JD may be dropped even if generally applicable | skills | 1 | Thornbury Sr PMM AI Workflows 06-25-26 | watch — 1 occurrence; needs-2nd-occurrence for auto-promotion |

Categories: routing · missed-evidence · claim-boundary · voice · skills · content.

---

## Entries

### Thornbury — Sr PMM AI Workflows (06-25-26)  ·  status: pending

**Folder:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26`

- **Base recommended → used:** Jordan Lee — Senior PMM (AI Product Marketing family) → same (agreed, mixed)
- **Accepted:** Option 2 summary (agent's top recommendation); [variant-ai] bullet swap; win-loss bullet partially retained; Birchwood first bullet; all 11 remaining skills in recommended order
- **Rejected / trimmed:**
  - AI bullet tail ('— a practitioner's use of AI tools, not ML engineering') dropped
  - Win-loss bullet: 'the messaging hierarchy' and 'not the roadmap owner' both removed; 'as an input partner' retained
  - Birchwood intern/people-management bullet removed entirely
  - 'Pricing & Packaging (Partner)' skill dropped (12 → 11 skills)
  - ', internal' dropped from positioning bullet qualifier
- **Summary edits:** 'use them pragmatically' added to AI-tools clause; 'honesty' dropped from closer ('bring that to an AI-native company' vs 'bring that honesty')
- **Claims softened/corrected:** None — all removals appear to be scope/voice adjustments, not corrections to factual claims
- **Evidence/story the agent missed:** None apparent; base was correctly identified
- **Style corrections made:** Multiple trims of defensive/over-hedged boundary language from bullets (AI tail, negative qualifier, scope clause); intern bullet removed for IC role
- **Open questions (5):** Q1 AI bullet tail (defensive vs. space), Q2 win-loss negative qualifier (over-hedged vs. length), Q3 messaging hierarchy (intentional scope vs. editorial), Q4 Birchwood intern (padding for IC roles), Q5 P&P skill (relevance vs. boundary vs. length)
- **Confirmed lessons:** _(pending candidate answers to Q1–Q5)_
- **Source files possibly affected:** 04-experience-bank.md (AI bullet variant, win-loss bullet variant), 00-job_application_agent.md (IC routing rule), 06-skills-quick.md (P&P routing note), 05-summary-quick.md (Family B AI-native closer)
- **Reconcile report:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`
- **Base/template candidate:** YES — AI product marketing + workflow-automation SaaS + anti-hype/grounded-claims culture. See source-update-queue.md Base/template candidates section.
