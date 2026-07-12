<!-- TEMPLATE — copy structure only. /cover-letter-intake stages a filled version for your review,
     then promotes it to the gitignored instance formatting-spec.md. Keep this file and config.json's
     "docx" section in sync — they describe the same output contract. -->
# Cover Letter Formatting Spec (.docx copy-paste source)

Purpose: the generated `.docx` is a **copy-paste source** for your own letter template (Pages,
Word, Google Docs — wherever your letterhead lives). You select the letter text, copy, and paste
into your template with a formatting-preserving paste (in Pages: regular **Paste**, NOT "Paste
and Match Style", which strips inline links). Formatting below should match your own resume /
letter template so nothing needs manual re-styling after paste.

## Your measured values (mirror these in `config.json` → `docx`)

- **Body font:** {{FONT, WEIGHT, SIZE — e.g. "Helvetica Neue, Regular, 10pt"}}
- **Text color:** {{HEX — e.g. "#3F3F3F"}} — applies to ALL text including hyperlinks
  (never default bright blue if your template doesn't use it)
- **Bold:** {{BOLD VARIANT — e.g. "Helvetica Neue Bold 10pt"}} — used for bullet lead-ins and the
  role title in the `Re:` line
- {{ANYTHING YOUR LETTERHEAD TEMPLATE OWNS — e.g. "the name banner and contact strip are part of
  the Pages template, not the letter body"}} — the .docx contains only the letter (date/Re: line
  through signature).

Tip: if you have a PDF of a letter or resume in your real template, the font sizes and fill colors
can be read out of the PDF itself — ask your assistant to measure them rather than guessing.

## Rules the generator applies

- Single line spacing; one blank line's worth of space between paragraphs (10pt space-after,
  0 space-before) — never hard-wrap prose with manual line breaks.
- Bullets: "•" with a 0.25" hanging indent; bold lead-in phrase ending with a period, then regular
  text continues on the same line.
- Inline links: real hyperlinks, **underlined, body text color** — not bright blue, unless your
  template wants that.
- No headers/footers, no page-margin fiddling (you paste the body only).
- The generator emits typographic quotes/apostrophes directly so the paste is clean.

## Church-and-state rule (do not break)

**The .docx is always exactly what the agent produced — you never edit it.** Your edits happen
in your own editor, and the version you submit is always a PDF. That makes:
- `.docx` (or `_cl_work/final.md`) = the agent's final recommendation (learning baseline)
- submitted PDF = ground truth of what you actually sent

The post-submission reconcile pass diffs the two; the delta IS your feedback. Nothing else in
the folder should be treated as "final".

## Regenerating

```
.venv/bin/python3 04-TAILOR/cover-letter/make_cover_letter_docx.py path/to/letter.md -o "path/to/<Your-Name>-CoverLetter - Company - Role.docx"
```

If you hit paste friction (wrong size, spacing, link loss), fix it HERE and in `config.json` —
this file is the single source of truth for output formatting.
