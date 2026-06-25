# Arabic (MSA) UI Chrome Conventions — Quranic Universal Audio

**Status: LOCKED.** This is the authoritative reference for translating UI chrome to Modern Standard Arabic. Every decision below is final. Downstream translator agents apply these rules without re-deciding. "Chrome" means UI labels, buttons, headers, tooltips, empty states, toasts, confirmations, table headers, filter chips, menu items — everything that is *not* Quranic content, reciter data, or technical identifiers.

The English source voice (PRODUCT.md / DESIGN.md) is **"precise and unadorned, no marketing, no warmth-theater. Labels are nouns; verbs are imperative. Numbers are real and contextual."** The Arabic must be the register-equivalent of that — not a different personality in another language.

---

## 1. Variety & Register

- **Modern Standard Arabic (الفصحى), formal-neutral.** No dialect (no Egyptian, Levantine, Gulf, Maghrebi forms). Ever. A Moroccan researcher and a Saudi maintainer must read the same string identically.
- **Concise and unadorned.** No خطابة (rhetorical/sermonic flourish), no rhyming saj‘, no honorific padding, no devotional embellishment in chrome. The reverence in this product is carried by *surfacing reciter names and Quranic text correctly* — never by decorating the buttons. A button that says "احفظ" is correct; "احفظ عملك المبارك" is a firing offense.
- **No marketing voice.** No "اكتشف", "استمتع بـ", "مرحبًا بعودتك", exclamation marks, or emotive adjectives. Mirror the English ban on "Welcome back!" warmth-theater.
- **Actions = imperative verbs.** Buttons and action menu items use the bare imperative (الأمر), masculine singular form as the *neutral grammatical default* (see §9 — this is grammatical gender, not addressing a man): "احفظ" (Save), "انشر" (Publish), "تراجع" (Undo), "طالِب" / "قدِّم مطالبة" (Claim).
- **Labels = nouns / verbal nouns (مصدر).** Tabs, headers, table columns, and field labels are nouns or maṣdar, not sentences: "القارئ", "النشر", "المراجعة", "الأذونات", "التقطيعات". Prefer the maṣdar over a finite verb for a *label* ("النشر" not "ينشر"; "الحفظ" only if naming the concept, "احفظ" for the action button).
- **No filler.** Drop "الرجاء", "من فضلك", "قم بـ". Write "احذف العنصر" not "الرجاء القيام بحذف العنصر". The compound "قم بـ + مصدر" is banned — use the plain imperative verb.
- **Sentence case equivalent.** Arabic has no case; keep strings tight and unpunctuated unless the string is a full sentence (confirmations, errors, empty-state prose).
- **Consistency over elegance.** If two phrasings are both correct, the one already in the glossary wins. Never introduce a synonym for a glossary term.

---

## 2. Numerals — LOCKED: Western (0–9)

**Decision: Western Arabic numerals (0 1 2 3 4 5 6 7 8 9), aka "Arabic numerals", everywhere in chrome.** Do **not** use Eastern Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩).

Rationale (this is a technical operator tool, not a literary surface):
- The app is dense with **IDs, timestamps, chapter/verse references, bitrates, codes, counts** that live in `tabular-nums` mono. Those are locked LTR-Western regardless (§7). Mixing Arabic-Indic digits into chrome counts while data digits stay Western produces a jarring two-numeral-system interface and breaks visual alignment in tabular columns.
- The DESIGN.md type system uses `font-variant-numeric: tabular-nums` for aligned figures; the mono stack (`SF Mono`, `JetBrains Mono`, Consolas) renders Western digits as designed tabular glyphs. Arabic-Indic tabular support in those faces is unreliable.
- Researchers, contributors, and maintainers in this space read surah:ayah as "2:255", bitrate as "128 kbps", durations as "00:03:41". Forcing "٢:٢٥٥" fights muscle memory.
- One numeral system for the whole product = zero cognitive switching cost. That is the KISS choice.

**Locked rule:** All digits — in chrome counts, in data, in IDs, in timestamps — are **Western 0–9**. Numerals are always rendered LTR even inside an Arabic string (the bidi algorithm does this automatically; see §8). Never substitute Arabic-Indic digits via CSS `font-feature-settings` or a numeral-shaping filter.

---

## 3. Tashkeel (Diacritics) — LOCKED: none in chrome

**Decision: NO tashkeel (harakāt) in UI chrome.** Reserve fully/partially diacritized text exclusively for Quranic content (rendered in the DigitalKhatt face), which is out of scope for chrome translation.

- Chrome strings are written **undiacritized** ("plain rasm"): "القارئ", "احفظ", "المراجعة" — never "القَارِئ", "اِحْفَظْ".
- Tashkeel in chrome adds visual noise, fights the "calm, quiet surface" principle, can render inconsistently across the system sans stack, and is simply not how native technical UIs are written.

**The one permitted exception — disambiguation harakah.** Add the *minimal* harakah (usually a single šadda, a fatḥa, or a sukūn) **only** when its absence creates a genuine, in-context meaning collision that the surrounding UI cannot resolve. Apply sparingly and document each case in the glossary, do not sprinkle freely. Canonical cases:
- A verb-vs-noun or active-vs-passive collision in an action label where context does not disambiguate (e.g. distinguishing an imperative from a maṣdar when both could sit on a button).
- "مُحدَّث" (updated, passive participle) vs "مُحدِّث" (updater) — diacritize the distinguishing harakah if both could appear.

If you reach for a disambiguation harakah, first try to **reword** so no harakah is needed (preferred). Diacritize only when rewording would compromise the term. When in doubt: no tashkeel.

---

## 4. Punctuation — LOCKED

Use Arabic-script punctuation marks in Arabic chrome. They are visually weighted for the script and keep the RTL reading correct.

| Mark | Use | Codepoint |
|---|---|---|
| **،** Arabic comma | All commas in Arabic prose/lists | U+060C |
| **؛** Arabic semicolon | Clause separation in sentences | U+061B |
| **؟** Arabic question mark | All questions (mirrored glyph) | U+061F |
| **.** Full stop | Same as Latin (no distinct Arabic period) | U+002E |
| **:** Colon | Same as Latin; in label:value pairs the value side keeps its own direction (§8) | U+003A |
| **%** Percent | Keep Latin `%`; the Arabic percent sign ٪ (U+066A) is **not** used — consistency with Western numerals | — |

**Quotation marks.** Use Arabic guillemets **«…»** (U+00AB / U+00BB) for quoting a name, a reciter, a verse fragment, or a UI term inside Arabic prose: «احفظ»، «تحت المراجعة». Do **not** use straight ASCII `"…"` or English curly quotes in Arabic text. (Inside code/JSON examples this guide shows ASCII for clarity — that is documentation, not output.)

**Brackets/parentheses.** Use standard parentheses `(` `)`. The bidi algorithm auto-mirrors them in an RTL run, so type them in logical order; do not manually swap to `)` `(`. When a parenthetical contains LTR content (a code, a Latin transliteration, a number), isolate it (§8) so the brackets sit correctly.

**Ellipsis / progress.** Use a single `…` (U+2026), not three dots. "جارٍ الحفظ…" (Saving…).

**No exclamation marks** in chrome (register rule §1), except a genuine destructive-action warning where the source uses one — and even then prefer a plain declarative.

---

## 5. Domain Glossary — LOCKED (en → ar)

This is the binding term list. **Use these exact forms.** Do not introduce synonyms. Two buckets: **(A) native Arabic Quranic-science terms** — these are *the* correct Arabic words, not translations, and must be used; and **(B) UI/tech terms** — decided per term as translate / transliterate / keep-English.

### A. Quranic-science terms (native Arabic — use the real term)

| English (source) | Arabic (LOCKED) | Notes |
|---|---|---|
| Reciter | **القارئ** (pl. **القُرّاء** / "قُرّاء") | The subject of the product. Singular القارئ, plural قُرّاء. |
| Recitation | **التلاوة** | The act/audio of reciting. Use تلاوة, not "قراءة صوتية". |
| Surah / Chapter | **السورة** (pl. **السُّوَر**) | Always سورة, never the calque "فصل". "Chapter" in the UI = سورة. |
| Ayah / Verse | **الآية** (pl. **الآيات**) | Always آية, never "بيت" or "جملة". |
| Mushaf | **المصحف** (pl. **المصاحف**) | Keep المصحف. |
| Riwayah | **الرواية** (pl. **الروايات**) | The transmission (e.g. Ḥafṣ ‘an ‘Āṣim). Keep الرواية. |
| Qira’a / Qira’ah | **القراءة** (pl. **القراءات**) | The reading tradition. Note collision with generic "reading"; in this product القراءة = the qira’ah term. |
| Tilāwah style / recitation style | **أسلوب التلاوة** | "style" in the taxonomy = أسلوب. |

> These are domain identity. Surfacing them correctly is part of "treating the recordings as objects of devotion" (PRODUCT.md). Never substitute a generic technical synonym.

### B. UI / tech terms (decision applied per term)

Decision key: **[T]** = translate to Arabic · **[X]** = transliterate to Arabic script · **[E]** = keep English/Latin as-is.

| English (source) | Arabic / form (LOCKED) | Decision | Notes |
|---|---|---|---|
| Dashboard | **لوحة التحكم** | T | The Dashboard tab. Not "داشبورد". |
| Catalog | **الفهرس** | T | The reciter/deliveries catalog. "الفهرس" (index/catalog). Not "كتالوج". |
| Timestamps | **الطوابع الزمنية** | T | The Timestamps tab (waveform/analysis). |
| Segment (one) | **المقطع** (pl. **المقاطع**) | T | A single alignment segment. |
| Segments (the editor tab) | **التقطيعات** | T | The editor tab name. Use التقطيعات for the tab/editor concept; المقطع/المقاطع for individual units. Keep this distinction. |
| Waveform | **الموجة الصوتية** | T | The rendered waveform. |
| Peaks | **قمم الموجة** | T | Waveform peaks data. (When labeling the raw artifact technically, "بيانات الموجة" is acceptable; default to "قمم الموجة".) |
| Audio | **الصوت** | T | The audio (file/stream). "الصوت", not "أوديو". |
| Bitrate | **معدّل البِت** | T | kbps stays Latin: "معدّل البِت: 128 kbps". |
| Review | **المراجعة** | T | Noun (the queue/act). Verb "راجِع". |
| Release | **الإصدار** (pl. **الإصدارات**) | T | A dataset release. Noun الإصدار; verb "أصدِر". |
| Publish | **النشر** / imperative **انشر** | T | Label النشر, button انشر. |
| Draft | **مسوّدة** | T | Draft state. |
| Claim (verb) | **طالِب بـ** / **قدِّم مطالبة** | T | Action of claiming a reciter. Button: "طالِب بالقارئ" or short "طالِب". The claim record (noun) = **المطالبة**. |
| Claim (noun, the record) | **المطالبة** | T | — |
| Permissions | **الأذونات** | T | The Permissions tab / capability matrix. |
| Capability (in the matrix) | **القدرة** (pl. **القدرات**) | T | The data-driven capability rows. |
| Role (tier) | **الدور** (pl. **الأدوار**) | T | Maintainer/Owner/etc. tiers. |
| Sign in | **تسجيل الدخول** | T | Noun label. |
| Sign out | **تسجيل الخروج** | T | Noun label. |
| Save | **احفظ** | T | Imperative button. |
| Undo | **تراجع** | T | Imperative button. Redo = **أعِد**. |
| Dataset | **مجموعة البيانات** | T | The published dataset. |
| Filter | **التصفية** / chip verb **صفِّ** | T | Faceted filters. Noun التصفية, "المرشّحات" acceptable for the set of filter chips. |
| Search | **البحث** / imperative **ابحث** | T | — |
| Activity / Audit | **سجل النشاط** / **سجل التدقيق** | T | Activity rail / audit trail. |
| Request (intake) | **الطلب** (pl. **الطلبات**) | T | The Requests admin queue. |
| Maintainer | **المشرف** (pl. **المشرفون**) | T | The maintainer tier. |
| Owner | **المالك** (pl. **المالكون**) | T | The owner tier. |
| Contributor | **المساهم** (pl. **المساهمون**) | T | The contributor tier. |
| Admin | **الإدارة** (surface) / **المسؤول** (person) | T | The Admin surface = الإدارة; an admin person = مسؤول. |
| Delivery (taxonomy unit) | **النسخة** / **الإصدارة الصوتية** | T | A mushaf×riwayah×style×source combination. Use **النسخة** consistently for "delivery" to avoid collision with "الإصدار" (Release). Lock: delivery = النسخة, release = الإصدار. |
| Lifecycle state | **الحالة** | T | The state pill concept. |
| Published (state) | **منشور** | T | State label. |
| Under review (state) | **تحت المراجعة** | T | State label. |
| Available (state) | **متاح** | T | State label. |
| Requested (state) | **مطلوب** | T | State label. |
| Discarded (state) | **مهمَل** | T | State label (reads as *demoted*, never *error*). |
| Error (state/text) | **خطأ** | T | — |
| Mark ready | **علّم كجاهز** | T | The "send marked-ready work back" action. |
| Loop (a verse) | **كرِّر** | T | Timestamps analysis control. |
| Speed | **السرعة** | T | Playback speed. |
| Translation(s) | **الترجمة / الترجمات** | T | The translations globe. |
| Word / Letter / Phoneme (tiers) | **الكلمة / الحرف / الصوت (الفونيم)** | T | Analysis tiers. "الفونيم" transliterated is acceptable beside "الصوت"; prefer **الصوت** for the tier label, keep "(فونيم)" only if disambiguation is needed. Letter = الحرف. |
| HuggingFace / HF | **Hugging Face** | E | Keep Latin brand name. Never transliterate. |
| GitHub | **GitHub** | E | Keep Latin. |
| OAuth | **OAuth** | E | Keep Latin (protocol name). |
| ID | **المعرّف** (label) / value Latin | T | Label translated; the ID value itself is LTR Latin/numeric (§7). |
| URL / link | **الرابط** | T | The URL value stays LTR Latin. |
| kbps / Hz / MB / ms | keep Latin units | E | Units ride with their Western number, LTR-isolated. |

**Transliteration policy (when [X] applies):** we transliterate **only** established brand/protocol names that have no Arabic and that users recognize by sound — and in practice this product has none we transliterate (Hugging Face / GitHub / OAuth stay Latin **[E]**, not Arabic-script). So the effective rule is binary: **translate it, or keep it Latin.** Do **not** invent Arabic-script spellings of "dashboard/catalog/segment" — those are translated. This avoids the half-Arabized "داشبورد/سيجمنت" register that reads as unprofessional.

---

## 6. Do-Not-Translate List — LOCKED

These pass through **verbatim, untranslated**:

- **The product name** — "Quranic Universal Audio" and "Inspector" stay in Latin. Do not translate or transliterate the product/app name in chrome. (If a future tagline needs Arabic, that is a separate, explicitly-approved string — not a translator's call.)
- **Reciter names** — rendered as the data provides (Arabic + Latin transliteration paired, from the catalog/API). Translators never touch, reorder, or "fix" a reciter name. The Arabic form comes from data; never machine-transliterate one.
- **Surah names data** — already bilingual from the Quran API (Arabic name + Latin/English name + number). Pass through; do not re-translate surah names in data rows. (The *word* "Surah/Chapter" as a UI label = سورة per §5; the surah *name* "Al-Fātiḥah" is data, untouched.)
- **Quran text** — every glyph of Quranic content is data, rendered in DigitalKhatt, never touched by chrome translation, never paraphrased.
- **Proper nouns / brand names** — Hugging Face, GitHub, OAuth, Vite, Svelte, SQLite, CDN names, etc. stay Latin.
- **Technical identifiers** — slugs, file paths, job IDs, commit SHAs, version tags (v0.3.0), env var names, capability keys, chapter/verse refs as codes (2:255), timestamps (00:03:41), bitrates, hashes. All Latin/Western, LTR (§7).
- **The word "Quran" itself** — when "Quran" appears as a standalone word in Arabic chrome, write it **القرآن** (with the standard Arabic form, including the maddah/hamza of the established spelling — this is the one place the established orthographic shape is kept). "Quranic" as an adjective → "القرآني / القرآنية". The product name "Quranic Universal Audio" stays Latin (above); the common-noun "القرآن" inside an Arabic sentence is Arabic.

---

## 7. Data, IDs, Timestamps, Codes — LOCKED LTR + Western

Regardless of the chrome being Arabic, the following are **always Western digits, Latin script where applicable, and forced LTR**:

- Numeric IDs, slugs, hashes, commit SHAs, version tags.
- Timestamps and durations: `00:03:41`, `2025-06-25`.
- Surah:ayah references as codes: `2:255`, `114:6`.
- Technical units and values: `128 kbps`, `44100 Hz`, `12.4 MB`, `40 ms`.
- File paths, URLs, env vars, capability keys.

These are isolated from the surrounding Arabic with bidi isolation (§8) so the Arabic does not reorder them. Never localize a code's digits to Arabic-Indic. Never insert Arabic punctuation inside a code.

---

## 8. Interim BiDi Handling — LOCKED (chrome stays LTR in workflow 1)

**Context:** The full RTL layout flip is a *later* workflow. In the **first** workflow, Arabic strings ship into chrome that is still **LTR-positioned**. Arabic text will therefore sit inside LTR-laid-out elements. This is expected and acceptable for the interim.

**Locked rules:**

1. **Pure-Arabic text nodes: trust the browser bidi algorithm.** A text node that is entirely Arabic (no Latin/digits) renders correctly RTL *within its own box* via the Unicode Bidirectional Algorithm with no intervention. Do not add per-character markup. The element's box stays LTR-positioned (left-aligned); the Arabic glyphs inside read right-to-left correctly. **Left-aligned Arabic is the accepted interim look** until the RTL layout workflow lands — do not try to hack `text-align: right` string-by-string; that is the RTL workflow's job, done holistically.

2. **Mixed Arabic + Latin/number/code strings: ISOLATE the foreign run.** Any string that mixes Arabic with a Latin word, a number, a code, an ID, a URL, or a unit **must** bidi-isolate the non-Arabic run so the bidi algorithm does not visually scramble the LTR layout. Use any of:
   - `<bdi>…</bdi>` around the embedded run (preferred in markup),
   - `dir="auto"` on the containing element when its base direction should follow its content,
   - `unicode-bidi: isolate` in CSS for a styled span.

   Example: a count like "‎128 kbps" inside "معدّل البِت: 128 kbps" — wrap the value: `معدّل البِت: <bdi>128 kbps</bdi>`. A reciter row mixing Arabic name + Latin transliteration + numeric ID isolates each foreign run.

   Without isolation, a trailing number or a parenthesis can "jump" to the wrong side and mangle alignment in the still-LTR chrome. **This is the single most important interim rule** — when in doubt, isolate.

3. **For interpolated values in messages:** wrap every `{value}` that can be Latin/numeric/code in isolation at the template level, so translators don't have to think per-string. (e.g. message templates ship the placeholder pre-wrapped in `<bdi>` or rendered through an isolating component.)

4. **Do not** manually insert RLM/LRM marks (‏/‎) into translated strings as a fix. Isolation (`<bdi>`/`dir="auto"`/`unicode-bidi: isolate`) is the locked mechanism; stray directional marks rot and are invisible in review.

5. **Punctuation in mixed strings:** type punctuation in logical order and let isolation + the bidi algorithm place it. Do not pre-mirror brackets.

**Expectation to set with downstream:** in workflow 1, Arabic chrome will look left-aligned and sit in LTR containers. That is correct and signed-off. The job in workflow 1 is *accurate strings that don't visually mangle the layout*, achieved via isolation — **not** a flipped layout. The RTL flip is workflow 2.

---

## 9. Gender & Formality of Address — LOCKED

- **Impersonal and gender-neutral by default.** The product addresses no one by gender. Do not write second-person gendered address ("أنتَ"/"أنتِ", "قُمتَ"/"قُمتِ").
- **Actions:** use the bare imperative in the **masculine-singular grammatical default** ("احفظ", "انشر", "احذف"). In Arabic UI convention this is the *unmarked* form — it is grammatical default, not a statement that the user is male. Do **not** ship dual gendered variants ("احفظ/احفظي"); that is noise and the product is impersonal.
- **Prefer agentless / nominal constructions for system messages and confirmations**, which sidesteps gendered verbs entirely:
  - Saving/progress: **"جارٍ الحفظ…"** (Saving…) — not "أنت تحفظ".
  - Result: **"تم الحفظ"** (Saved), **"تم النشر"** (Published), **"تعذّر الحفظ"** (Couldn't save) — passive/agentless, gender-free.
  - Counts/status: nominal — "3 مقاطع محدّدة" (3 segments selected), not a verb addressed to the user.
- **Confirmations:** state the consequence impersonally, ask with ؟:
  - "حذف هذا المقطع؟ لا يمكن التراجع عن هذا الإجراء." (Delete this segment? This can't be undone.)
  - Buttons: "احذف" / "إلغاء". Not "هل أنت متأكد؟" warmth-padding — match the unadorned English register.
- **No honorifics** (no "حضرتك", "سيدي"). The tool is a terminal, not a concierge.
- **Tier/role nouns** default to the conventional masculine form as the unmarked label (المشرف، المالك، المساهم); these name a *role*, not a person's gender.

---

## 10. Pluralization — LOCKED: ICU plural messages mandatory

Arabic distinguishes **six** CLDR/ICU plural categories: **zero, one, two, few, many, other**. Naive `count + " " + noun` concatenation is **forbidden** — it is grammatically wrong in Arabic for most counts.

**Locked rule:** every count-bearing string is an **ICU MessageFormat plural message** with all six Arabic categories authored. Translators must fill `zero/one/two/few/many/other` — not just `one/other`. The number interpolates as Western digits, bidi-isolated.

Arabic category boundaries (for `n`): **one** = 1; **two** = 2; **few** = 3–10 (and 103–110, …); **many** = 11–99 (and 111–199, …); **zero** = 0; **other** = fractions and the residual (e.g. 100, 101, 102, 1000…). Author all six; the ICU runtime selects.

**Example — "{n} segments" (مقاطع):**

```
{n, plural,
  zero  {لا مقاطع}
  one   {مقطع واحد}
  two   {مقطعان}
  few   {# مقاطع}
  many  {# مقطعًا}
  other {# مقطع}
}
```

(`#` renders the count; the runtime must emit it as a bidi-isolated Western numeral. If your renderer doesn't auto-isolate `#`, wrap the message output so the digit is isolated per §8.)

**Example — "{n} reciters" (قُرّاء):**

```
{n, plural,
  zero  {لا قُرّاء}
  one   {قارئ واحد}
  two   {قارئان}
  few   {# قُرّاء}
  many  {# قارئًا}
  other {# قارئ}
}
```

Never approximate by reusing the English `one/other` pair for Arabic. A string like "23 reciters available to review" (PRODUCT.md's real-number example) must route through the plural machinery: e.g. `{n, plural, …} متاح للمراجعة` with the count phrase pluralized and the trailing predicate agreeing.

> The on-disk message-format JSON shape for these is in `project-conventions.md` §5 (the `"match": { "count": "plural" }` + `"count=zero"`…`"count=other"` keys). This section is the *Arabic linguistic* spec; that section is the *file shape*.

---

## 11. Length / Expansion — LOCKED

- The DESIGN.md type scale is a **fixed ladder** (11.5 · 13.5 · 14 · 16 · 22 · 32 px), no fluid shrink. Chrome does not reflow type size to fit a longer translation. **Therefore translators keep labels tight.**
- Arabic can run **longer** (more characters for the same concept) **or shorter** than English. Both happen:
  - Prefer the shorter correct synonym for tab labels, chips, and buttons (single word where the glossary allows: "النشر", "المراجعة", "التصفية").
  - Avoid maṣdar chains and prepositional padding in fixed-width chrome.
- **Flag, don't silently truncate.** If the locked Arabic term cannot fit a fixed-size element (a narrow filter chip, a state pill at `2px 8px`, a dense table header), the translator **flags the string** for the design owner rather than (a) abbreviating with a non-standard contraction, (b) dropping a glossary term, or (c) inventing a shorter synonym. Pills and chips are the tightest budget — check those first.
- **Mono/tabular columns** (IDs, timings, counts) do not expand — they're Western digits in `tabular-nums` and width-stable; the Arabic *header* above them is the only variable, so keep headers short.
- Never solve overflow by removing tashkeel-that-isn't-there or by switching to a dialect contraction. Overflow is a layout flag, not a register compromise.

---

## 12. Quick checklist for a translator agent (apply to every string)

1. Is it data / ID / reciter name / Quran text / product name / brand? → **don't translate** (§6, §7).
2. Is it an **action**? → imperative, neutral form, glossary verb (§1, §9).
3. Is it a **label**? → noun/maṣdar, glossary term, kept tight (§1, §11).
4. Does it contain a **count**? → ICU plural, all 6 Arabic categories (§10).
5. Does it **mix Arabic + Latin/number/code**? → bidi-isolate the foreign run (`<bdi>` / `dir="auto"`) (§8).
6. **Digits** → Western 0–9, always (§2).
7. **Tashkeel** → none, unless a documented disambiguation harakah (§3).
8. **Punctuation** → Arabic ، ؛ ؟ and «…» (§4).
9. **Gendered/personal phrasing?** → rewrite impersonal/agentless ("تم…", "جارٍ…") (§9).
10. **Won't fit a fixed element?** → flag it, don't butcher it (§11).
