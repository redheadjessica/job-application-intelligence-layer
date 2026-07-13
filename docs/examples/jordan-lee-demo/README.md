# Jordan Lee — Synthetic Demo Kit

> ⚠️ **100% FICTIONAL SYNTHETIC DEMO. NOT REAL DATA.**
> Everything in this folder is invented for demos, screenshots, and end-to-end testing.
> "Jordan Lee" is not a real person. The companies, roles, resumes, metrics, and job posts are
> fabricated. **Never** put a real resume, real job application, real company, real person, or any
> real job-search material in here.

## What this is

A committed, **public-safe** demo kit for JAIL. It serves two jobs at once:

1. **A synthetic end-to-end test bed** for the V2 workflow (intake → prep → rank → tailor → archive → reconcile).
2. **A source of reusable, public-safe demo artifacts** (ranking spreadsheet, tailored draft, archive/reconcile samples) and the staging material for README/website screenshots.

Because it is 100% fictional, the artifacts here can be committed and shown publicly without leaking anyone's job search.

## Who Jordan Lee is (high level)

**Jordan Lee — Senior Product Marketing Manager.** Targeting **AI Product Marketing, GTM Strategy, and Lifecycle/Growth** roles at AI / developer-tooling companies.

- B2B SaaS / workflow-tooling PMM background (senior individual contributor).
- Has worked on launches, positioning, customer research, lifecycle messaging, sales enablement, and adoption programs.
- Has used AI tools to accelerate research, messaging exploration, enablement drafts, and competitive analysis.
- Wants to move into AI-native product marketing / GTM strategy roles.
- **Has not** owned core ML product strategy. **Has not** led a large team.
- Supported launches and GTM work — but should **not** overclaim executive ownership of every launch.

### Truth boundaries (what makes the honesty story visible)

- ✅ Used AI workflows internally · ❌ don't imply Jordan built ML systems.
- ✅ Partnered with product · ❌ don't imply Jordan owned the product roadmap.
- ✅ Led positioning / messaging work · ❌ don't imply Jordan owned all company strategy.
- Launch / adoption metrics are **fictional, internally consistent, and clearly part of the synthetic demo** — never presented as real.
- Don't inflate people-management scope.

## Why PMM / GTM (not strategic finance)

- Still clearly synthetic and not the author.
- The name is gender / ethnically ambiguous (kept intentionally).
- PMM/GTM produces stronger, more legible public screenshots than finance.
- More interesting for an applied-AI / AI-tooling audience.
- Lets the demo show judgment, positioning, GTM strategy, workflow adoption, AI-adjacent claims, and truth boundaries.
- Deliberately distant from any prior real testing material.

## What this folder IS for

- Holding **committed synthetic fixtures** (Jordan's materials, config, job posts) → `fixtures/`.
- Holding **committed synthetic outputs** (ranking CSV + `.xlsx`, one tailored draft, one archive summary, one reconcile sample, a prep-report sample) → `expected-outputs/`.
- Documenting **how to stage** these fixtures into the real runtime folders for screenshots and E2E testing → `staging/`.

## What this folder is NOT for

- ❌ Any real candidate data, real resume, real LinkedIn, real applications, or real job-search materials.
- ❌ Any real person's resume (including the author's or anyone they know).
- ❌ Real company names or real / expiring job-post URLs.
- ❌ Runtime / private generated files — those stay gitignored (see "Safety rules").

## Safety rules (read before adding anything)

- **Synthetic only.** If it describes a real person, company, or job, it does not belong here.
- **Do not use real candidate data here.** Not the author's, not anyone's.
- **Do not force-add runtime / private paths.** Never `git add -f` anything under `__READY TO REVIEW/<batch>/`, `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/`, `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/`, `jail.config.json`, or `05-SUBMITTED-APPLICATIONS/`. Those are gitignored on purpose. Commit demo data **here** (in `examples/`) instead.
- **Screenshots of runtime folders are fine — only when populated with synthetic Jordan Lee data**, then cleaned up. See `staging/README.md`.
- **Real-URL smoke tests are separate and disposable** — never committed, never screenshotted.

## Planned artifact map

```text
docs/examples/jordan-lee-demo/
  README.md                  ← you are here
  fixtures/                  ← committed synthetic INPUTS
    (Jordan's resume(s), brag doc, target JD,
     5 synthetic job posts, example jail.config.json,
     instance files: scoring-card, candidate-profile,
     profile, experience-bank, summary/skills quick refs)
  expected-outputs/          ← committed synthetic OUTPUTS
    (rankings CSV, rankings .xlsx, one tailored markdown,
     one archive-summary.md, one reconcile sample,
     prep-report sample)
  staging/                   ← how to stage fixtures into runtime + clean up
    README.md
  screenshots-notes.md       ← practical capture checklist (state → window → crop → PNG)

docs/screenshots/            ← committed screenshot PNGs (synthetic content only)
```

(Folders are scaffolded now; content arrives in later V2.1 units.)

## Notes on specific artifacts

- **The `.xlsx` is an approved committed demo artifact.** The ranking spreadsheet is a core product output; committing it (small, inspectable) lets public reviewers open it. It renders deterministically from the committed CSV via `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/make_rankings_xlsx.py`.
- **Screenshots** captured from this kit are committed under **`docs/screenshots/`** (visible content must be synthetic).
- **Real-URL smoke** (live fetch) is a later, separate, disposable step — see `docs/testing-and-caveats.md`.

## Status

Scaffold created in **V2.1 Unit 1**. Synthetic content (fixtures, outputs, screenshots) is added in later units. Nothing here is generated or run yet.
