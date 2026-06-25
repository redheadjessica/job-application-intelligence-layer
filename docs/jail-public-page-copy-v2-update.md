# JAIL public page, V2 copy updates

Additive notes for the website-repo agent. This does **not** replace `jail-public-page-copy.md`. It lists the lines that should change on redheadjessica.com/jail now that V2 has shipped, including the header, the opening, and the future-improvements list. The website source lives in a separate repo, so nothing here edits it directly.

Items 1 through 6 are the real changes. Items 7 and 8 are optional. Everything matches the existing page voice and uses plain punctuation (no em dashes).

---

## 1. Eyebrow and opening, lead with Claude  (core, new)
**Where:** the eyebrow line (currently "Open Source Project") and the opening paragraphs under the title.
**Why now:** "a local AI-assisted workflow" tells a normal reader almost nothing. Claude is a name people recognize, so saying it up front makes the whole project make sense in one line.

**Eyebrow, pick one:**
- An Open Source Claude Code Project  *(recommended)*
- Open Source. Built to run with Claude.
- Open Source. Claude Code.

**Opening copy:**

A local workflow I built to run with Claude, the AI assistant from Anthropic. I made it during my own job search to rank roles, tailor resumes, and apply with a lot less grind and a lot more truth.

Applying to jobs should not feel like serving time. JAIL helps you review a batch of roles, rank them by fit, pick the strongest resume base, and generate tailored notes you can use to finish stronger applications faster. You run it on your own computer inside Claude Code, which is Claude that can work directly with the files on your machine. If you have only ever used Claude in a browser, that is fine. The setup walks you through it.

---

## 2. Privacy note  (core)
**Where:** the "A quick privacy note" block in Get Started.
**Why now:** V2 added a template/instance split, so privacy is a built-in default the repo handles for you.

**New copy:**

A quick privacy note. JAIL keeps your private materials on your computer. The repo only tracks the shared templates and code, so the files JAIL fills in with your real resume, along with your raw materials and submitted applications, stay out of git by default. If you fork it, keep the fork private, and don't put personal resumes, notes, or salary thinking in a public repo.

---

## 3. The /intake review gate  (core)
**Where:** the Get Started steps, where it tells you to run `/intake`.
**Why now:** V2 made intake stage a review folder you approve before anything is saved. It backs up the "you stay in control" promise.

**New copy:**

Once the folder is open in Claude Code, start with `/intake`. It reads your materials, gives you an honest read on your resume, and asks a few sharp questions. Then it drops proposed setup files into a review folder and stops. Nothing becomes your source of truth until you look it over and approve it.

---

## 4. Rank Roles  (core)
**Where:** the "Rank Roles" card under What It Does.
**Why now:** V2 made ranking relative to criteria you set yourself (pay, location and work setup, the lanes you want), not a fixed generic score.

**New copy:**

Review batches of roles and rank them by what actually matters to you. You set the criteria: pay range, location and work setup, the lanes you want, plus fit, desire, practicality, and how the market tends to read the role. You get back a sorted, color-coded spreadsheet showing where to start.

---

## 5. Reconcile line  (core)
**Where:** the "What You Get Back" list (the reconciliation bullet), plus one optional sentence nearby.
**Why now:** the current line ("when your materials change over time") describes the wrong trigger. Reconcile learns from what you actually submit.

**New list bullet (swap in):**

Reconciliation notes that learn from what you actually submitted

**Optional supporting sentence:**

After you send an application, JAIL can compare what it recommended against your final resume, note what you changed, and suggest updates for you to approve.

---

## 6. Possible Future Improvements, rewrite  (core)
**Where:** the "Possible Future Improvements" list under Maybe Someday.
**Why now:** three of the current items are too vague to mean anything ("better batching recommendations," "stronger final application packets," "easier reconciliation prompts"), and the screenshots item is already being built. This swaps in plain, real things.

**Remove:**
- More beginner-friendly setup screenshots  (being built now)
- Better batching recommendations  (unclear)
- Stronger final application packets  (unclear)
- Easier reconciliation prompts  (unclear)

**Keep the existing intro line, then use this list:**

Someday I might add:

- A finished, formatted resume file.
- Cover letter help.
- Help with application questions.
- An export of your ranked tracker straight to Google Sheets.
- Automating the learning loop after you apply. (Today, you have to run it yourself.)
- Maybe a way to help find roles in the first place, instead of you bringing all of them.

(The honest closing under the list, "No promises. This is not my full-time job," should stay.)

---

## 7. Truth section, the core rule  (optional, recommended)
**Where:** "Why Truth Is Part Of The Product."
**Why now:** gives the truth principle a concrete shape using the evidence-versus-direction split the system actually runs on.

**New copy (add as a short paragraph in that section):**

One rule sits under all of it. What you've actually done and where you want to go live in separate places. Your goals shape which roles you chase and how you frame your real strengths. They never quietly become claims about things you haven't done.

---

## 8. A light "how it works" line  (optional)
**Where:** near "Under The Hood / What It Does," as a small aside.
**Why now:** one honest technical line for readers who care, and it doubles as proof of how the thing is built.

**New copy:**

Under the hood, the boring, repeatable work runs as local Python. The judgment work runs as Claude Code agents, including a vetting step that scores the roles in parallel. You approve every word before anything goes out.

---

## What not to touch
Leave Current Limitations as it is, and keep the honest closing under the future list. That honesty is part of why the page works. These updates only sharpen what is already there.
