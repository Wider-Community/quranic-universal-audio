# Product

## Register

product

## Users

**Maintainers** (1–5 people). Own the catalog end-to-end: add reciters, claim alignment runs, publish to dataset, run admin overrides. Spend hours per session in long focused sweeps on a 27"+ monitor. Want operator craft — status at a glance, dense tables, audit trails, keyboard fluency. They are the project's quality bar; the UI should feel like their terminal: trusted, fast, no nannying.

**Contributors** (10–100 over project lifetime). HF-authed enthusiasts who claim one reciter at a time and review segment alignment in 30–90 minute sittings. They cross between roles: today they review; tomorrow they're an anonymous browser exploring what's available. They want a clear queue ("what can I claim?"), zero friction on sign-in/claim, and confidence that their work is being respected.

**Anonymous browsers**. Quran-recitation listeners, researchers, students of the dataset. They came in via a link, an HF dataset page, or a search engine. Some will become contributors; most won't. They want to *discover* — browse who is published, hear samples, understand how the catalog is organized, see the work in motion.

## Product Purpose

Inspector is the contribution surface for a long-running effort to produce word- and verse-level timestamps for every Quran recitation publicly available on the open web. The dashboard is the front door: a public catalog of 422 reciters across 864 deliveries (the same reciter on multiple mushafs × multiple sources × multiple CDNs), showing what's published, what's under review, what's waiting for a reviewer to claim, and what's queued for alignment.

Success: a first-time visitor lands on the dashboard and within seconds understands (a) the scope of the project, (b) which reciters they can listen to right now, (c) how to participate. A maintainer can navigate the same surface as fluently as their terminal — filter, find, act, audit.

The catalog is the product. The taxonomy is non-trivial (reciter × riwayah × style × recording context × source × channel × delivery) and the surface must honor it without becoming bureaucratic.

## Brand Personality

**Dense, but warm.** The interface holds the tension between Stripe-dashboard operator craft (status pills, audit trails, monospace technical detail, big-screen comfort, accent-on-restraint) and Are.na / Internet Archive archivist energy (content-first cards without templates, meta-rich, restrained typographic chrome, browse-as-discovery). It is contemplative without being slow, technical without being cold, inviting without being soft.

Voice is precise and unadorned. No marketing language, no hype, no "Welcome back!" warmth-theater. Labels are nouns where possible; verbs are imperative ("Claim", "Mark ready", "Publish"). Numbers are real and contextual ("23 reciters available to review", not "thousands of recitations").

The dataset is the work of dozens of reciters whose recordings are objects of devotion. Treat them that way — surface their names (Arabic and English) prominently, never hide them in a side column.

## Anti-references

- **Generic SaaS admin.** No hero-metric template (big number, small label, gradient accent). No identical icon-headline-text card grids. No blue-on-white "modern admin" reflex.
- **Heavy bureaucratic admin (Jira / ServiceNow energy).** No six-toolbar density-for-density's-sake, no breadcrumbs for navigation that doesn't branch, no "Edit columns" buttons by default.
- **Religious-site clichés.** No green-and-gold palette, no arabesque borders, no mosque silhouettes, no calligraphic flourishes used as ornament. Arabic typography is functional, not decorative.
- **Gamified / toy.** No streaks, badges, confetti, ratings stars, level-up animations. Contribution is its own reward; the system should not pretend it's Duolingo.

## Design Principles

1. **Catalog dignity.** This is a curated archive of Quran recitations, not a SaaS dashboard. Layout, language, and density honor the content first. The reciter's name (Arabic + Latin) and a play affordance for their work should be more visible than any status pill.

2. **Information without bureaucracy.** Dense data, but every column, pill, and chip earns its place. No status soup. Faceted filters with live counts (like the existing `HistoryFilters` pattern — dulled-out empty options, count chips) over hidden-behind-modal filters. The user sees what's possible without clicking.

3. **Reader trust.** Surface taxonomy and technical metadata confidently. Don't dumb-down — show the riwayah / style / source / bitrate when they matter. Reward attention. The audience includes researchers who *want* the full schema.

4. **Restraint over chrome.** Accents are tools, not decoration. The Arabic name, the mushaf badge, the waveform thumbnail, the state pill — these are the things that should sing. Everything else recedes.

5. **Warmth in typography, not in chrome.** Softness comes from typographic care (line height, tracking, Arabic + Latin pairing, attentive vertical rhythm), not rounded corners or pastel colors. The interface is dark and quiet; the work inside it is alive.

## Accessibility & Inclusion

- **WCAG AA target.** Contrast minimums met across all states (including dulled-empty filter pills, view-only mode, focus rings on dark backgrounds).
- **Color-blind safe state communication.** State pills combine hue + shape + label, never hue alone. Red/green never used as the sole differentiator.
- **Arabic + English first-class.** Reciter names render in both with correct font + bidi handling. RTL is preserved inside Arabic name fields without flipping the whole component. Latin transliteration is paired, never alone.
- **Keyboard fluency.** Every claim / filter / play action is reachable via keyboard. Maintainer-frequented surfaces (dashboard, admin) prioritize keyboard shortcuts.
- **Reduced motion respected.** All transitions degrade to instant when `prefers-reduced-motion: reduce`.
- **Long sessions.** Dark theme is shipped and correct for the workload (multi-hour review sittings). No flash-of-light on theme load, no white modals on dark surface.
