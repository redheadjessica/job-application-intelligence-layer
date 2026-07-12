<!-- Cover-letter intake review file — proposed, NOT yet saved. Promotes to: 04-TAILOR/cover-letter/config.json + formatting-spec.md. -->

# 5 - Config + Formatting

**What to check:** The signature is exactly how you sign. The .docx styling matches YOUR letter/resume template (so paste needs no re-styling). The lint knobs match your taste.

## Signature
- **signature_name:** {{exactly as they sign letters; also used in the .docx filename}}

## .docx styling (measured from {{their template/PDF, or "shipped defaults — no template provided"}})
- Font: {{font + size}}
- Text color: {{hex}}

## Lint knobs
- Links per letter: {{min–max, or "0 — no link strategy"}}
- Body word target: {{range}}
- Disabled shipped rules: {{list + why, or "none"}}
- Personal banned phrases: {{each with the evidence it came from, or "none yet"}}

## Proposed config.json
```json
{{the full JSON that will be promoted}}
```
