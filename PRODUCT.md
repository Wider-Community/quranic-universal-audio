# Product

## Register

product

## Users

The catalog is public; the workflow behind it is tiered. Four audiences, listed by how the product first meets them:

**Anonymous browsers.** Quran-recitation listeners, researchers, students of the dataset. They arrive from a link, an HF dataset page, or a search engine. They can browse the full catalog, hear any published recitation, and watch the timestamps come alive — no sign-in. Most never contribute; the product still has to earn their attention in the first few seconds. Some convert.

**Contributors.** HF-authed enthusiasts who claim one reciter at a time and review its segment alignment in 30–90 minute sittings. They cross between roles fluidly: today they hold a claim and fix boundaries in the editor; tomorrow they're an anonymous browser exploring what else is available. A contributor is any signed-in user without an elevated role row — the floor, not a special grant. They want a clear queue ("what can I claim?"), zero friction on sign-in and claim, and confidence their work is respected.

**Maintainers.** A small core who own the catalog end-to-end: add reciters, send marked-ready work back, run alignment and timestamps jobs, manage other maintainers, audit activity. They spend hours per session in long focused sweeps on a 27"+ monitor. They are the project's quality bar; the operator surfaces should feel like their terminal — status at a glance, dense tables, audit trails, keyboard fluency, no nannying.

**Owners.** Maintainers plus the keys: grant and revoke any role, tune the capability matrix per tier, cut dataset releases, edit any reciter regardless of claim. The role boundaries are data-driven — an owner can move what each tier is allowed to do from the Permissions tab — so the tiers above describe the *default* baseline, not a hard wall.

## Product Purpose

Inspector is the public front door and contribution surface for a long-running effort to produce word-, verse-, letter-, and phoneme-level timestamps for every Quran recitation publicly available on the open web. The catalog spans hundreds of reciters across many *deliveries* — the same reciter on a different mushaf × riwayah × recitation style × recording context × source × CDN. That taxonomy is the hard part, and the product exists to honor it without drowning in it.

Three public tabs, each with a distinct job and a distinct mood:

- **Dashboard — the front door.** A faceted catalog of deliveries grouped by reciter, with live filter counts and a per-reciter detail modal that times each combination through its lifecycle. Its job is to let the *scale and care* of the project speak through the data alone: a first-time visitor should feel, within seconds, how big this is, how much thought went into the taxonomy, what they can listen to right now, and how to take part. No hype, no hero metric — the catalog is the pitch.

- **Timestamps — where the magic is.** Everything fuses here: waveform, audio, word-by-word animation, letters, phonemes, verse tracking, translations, a filmstrip of the recitation, and analysis tools (loop a verse, isolate a tier, adjust speed). Underneath, a 60fps loop synchronizes thousands of timing boundaries against the playhead. The design's entire job is to hide that machinery: surface immense, simultaneous computation as one calm, unified, distraction-free frame so the listener relaxes into the recitation and *witnesses* the alignment rather than operating it. The tension between how much is happening and how quiet it feels is the point.

- **Segments — the workshop.** The full editor where reviewers and contributors fix alignment: trim, split, merge, re-reference, validate on save. Utilitarian and self-evident. It serves the task and gets out of the way; craft here is in density, keyboard speed, and trustworthy feedback, not atmosphere.

Success: an anonymous visitor grasps the project and hears a recitation in seconds; a contributor claims and reviews a reciter without friction; a maintainer drives the whole lifecycle as fluently as their terminal.

## Operator surfaces (secondary)

Behind the public tabs sits the machinery that keeps the catalog moving — an Admin surface, reached by maintainers and owners, with compartments for **Users** (roster, visitor stats, owner-only role picker), **Requests** (intake queue for new reciters/combinations and edit requests), **Reviews** (the marked-ready queue plus timestamps-job control), **Releases** (cutting dataset releases to GitHub and Hugging Face), and **Permissions** (the owner-only capability matrix). These are not the product's face, but they are part of it, and they inherit the same design language: operator craft, status legibility, audit-first. Design decisions should keep them coherent with the public surface, not treat them as throwaway internal tooling.

## Brand Personality

**Dense, but warm.** The interface holds the tension between Stripe-dashboard operator craft (status pills, audit trails, monospace technical detail, big-screen comfort, accent-on-restraint) and Are.na / Internet Archive archivist energy (content-first rows without templates, meta-rich, restrained typographic chrome, browse-as-discovery). It is contemplative without being slow, technical without being cold, inviting without being soft.

Voice is precise and unadorned. No marketing language, no hype, no "Welcome back!" warmth-theater. Labels are nouns where possible; verbs are imperative ("Claim", "Mark ready", "Publish"). Numbers are real and contextual ("23 reciters available to review", not "thousands of recitations").

The dataset is the work of dozens of reciters whose recordings are objects of devotion. Treat them that way — surface their names (Arabic and Latin) prominently, never hide them in a side column.

## Anti-references

- **Generic SaaS admin.** No hero-metric template (big number, small label, gradient accent). No identical icon-headline-text card grids. No blue-on-white "modern admin" reflex.
- **Heavy bureaucratic admin (Jira / ServiceNow energy).** No six-toolbar density-for-density's-sake, no breadcrumbs for navigation that doesn't branch, no "Edit columns" buttons by default.
- **Religious-site clichés.** No green-and-gold palette, no arabesque borders, no mosque silhouettes, no calligraphic flourishes used as ornament. Arabic typography is functional, not decorative.
- **Gamified / toy.** No streaks, badges, confetti, ratings stars, level-up animations. Contribution is its own reward; the system should not pretend it's Duolingo.
- **A media player that shouts.** On Timestamps, no visualizer flash, no neon EQ bars, no motion that competes with the recitation. The animation serves comprehension and calm, never spectacle.

## Design Principles

1. **Let the data speak.** This is a curated archive of Quran recitations, not a SaaS dashboard. On the Dashboard especially, the scope, the taxonomy depth, and the reciters' names carry the message — the layout's job is to present them confidently and get out of the way. The reciter's name (Arabic + Latin) and a play affordance should be more visible than any status pill.

2. **Calm over a deep engine.** The more computation a surface holds, the quieter it should look. Timestamps is the test: thousands of synchronized boundaries, multiple analysis tiers, a 60fps loop — surfaced as one unified, distraction-free frame. Complexity lives in the engine; the surface stays still so the listener can rest in the recitation.

3. **Information without bureaucracy.** Dense data, but every column, pill, and chip earns its place. Faceted filters with live counts over hidden-behind-modal filters; the user sees what's possible without clicking. No status soup.

4. **Reader trust.** Surface taxonomy and technical metadata confidently — riwayah, style, source, bitrate, phoneme tiers — when they matter. Don't dumb down. The audience includes researchers who *want* the full schema; reward attention.

5. **Each tab to its purpose.** One visual language, three intents: Dashboard invites and orients, Timestamps calms and reveals, Segments equips and disappears. Consistency of vocabulary, difference of mood.

6. **Warmth in typography, not in chrome.** Softness comes from typographic care (line height, tracking, Arabic + Latin pairing, attentive vertical rhythm), not rounded corners or pastel colors. The interface is quiet — dark by default, with a calm cool-paper light theme for those who prefer it; the work inside it is alive.

## Accessibility & Inclusion

- **WCAG AA target.** Contrast minimums met across all states (including dulled-empty filter pills, view-only mode, focus rings) in BOTH themes — the light theme darkens the accent and every state hue so they clear AA on a near-white surface.
- **Color-blind safe state communication.** State pills combine hue + shape + label, never hue alone. Red/green never the sole differentiator.
- **Arabic + English first-class.** Reciter names and Quranic text render in both with correct font and bidi handling. RTL is preserved inside Arabic fields without flipping the whole component. Latin transliteration is paired, never alone.
- **Keyboard fluency.** Every claim / filter / play / analysis-toggle action is reachable via keyboard. Maintainer-frequented surfaces (Dashboard, Admin, Segments) prioritize shortcuts.
- **Reduced motion respected.** All transitions — including the Timestamps animation chrome — degrade to instant when `prefers-reduced-motion: reduce`.
- **Long sessions.** Two themes ship: dark (the default, for multi-hour review sittings and relaxed listening) and a calm cool-paper light peer (header toggle, persisted). Both are flash-free on load — `data-theme` is set before first paint — so no flash-of-theme either way. See [`docs/reference/theming.md`](docs/reference/theming.md).
