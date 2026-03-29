# Distribution Channels

How to get Quranic audio data into the hands of users beyond the raw HF dataset and GitHub releases. These channels turn passive data into interactive experiences — no app install, no gigabyte downloads.

All channels below are enabled by the `sources` config (URL templates for 350+ reciters) and the HF `/filter` API (verse-level access without downloading the full dataset).

---

## Platform Bots

### Discord Bot

Discord natively supports audio file attachments with inline players. Muslim communities are already active on Discord.

**Interaction model:**
```
User:  /quran 2:255
Bot:   [Audio player: Ayat al-Kursi — Mishary Alafasi]
       بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ ...
       Word timestamps: 0:00.56 → 0:04.41

User:  /quran 2:255 reciter:minshawy
Bot:   [Audio player: Ayat al-Kursi — Al-Minshawi]
```

**Implementation:** ~50 lines using discord.py + URL templates from `sources` config. Fetch audio directly from CDN, send as attachment. Optionally include word timestamps as formatted text or embed.

**Features possible:**
- `/quran <surah>:<ayah>` — single verse with audio
- `/quran <surah>` — full chapter (by_surah URL from template)
- `/reciters` — list available reciters (from `sources` config)
- `/quran <ref> reciter:<name>` — specific reciter
- Voice channel streaming for group listening sessions

### Telegram Bot

Telegram has a rich inline audio player with waveform visualization. Massive user base in Muslim-majority countries (Turkey, Iran, Indonesia, Central Asia).

**Interaction model:**
```
User:  /quran 2:255
Bot:   [Inline audio player with waveform]
       Caption: Surah Al-Baqarah, Ayah 255 — Mishary Alafasi

User:  (inline mode) @quranbot 2:255
Bot:   [Inline result with audio — works in any chat]
```

**Implementation:** python-telegram-bot + URL templates. Use `sendAudio` API with CDN URL (Telegram fetches and caches the audio server-side — effectively a free CDN layer).

**Telegram-specific advantages:**
- **Inline mode** — works in any chat without adding bot to group
- **Audio caching** — Telegram caches sent audio server-side, subsequent sends are instant
- **Channels** — daily verse broadcasts to subscriber channels

### WhatsApp (Business API)

Largest messaging platform in Muslim-majority countries (Egypt, Saudi Arabia, Pakistan, Indonesia, Malaysia). Business API supports sending audio files programmatically.

**Considerations:**
- Requires WhatsApp Business API approval (higher bar than Discord/Telegram)
- Audio sent via `messages` endpoint with media URL
- Massive potential reach but more complex to deploy

---

## Developer Tools

### Client SDK (npm / PyPI)

A typed wrapper that abstracts away the HF dataset structure. This is the foundation that makes every other integration trivial.

**Python:**
```python
from quran_audio import QuranAudio

qa = QuranAudio()

# Discover reciters
reciters = qa.reciters(riwayah="hafs_an_asim", style="murattal")

# Get verse audio URL (direct CDN, no download needed)
url = qa.audio_url("mishary_alafasi", surah=2, ayah=255)

# Get verse with timestamps
verse = qa.verse("minshawy_murattal", surah=2, ayah=255)
print(verse.word_timestamps)  # [[1, 560, 960], [2, 960, 1640], ...]
print(verse.source_offset_ms)  # 42300

# Get chapter URL for gapless playback
chapter_url = qa.chapter_url("mishary_alafasi", surah=2)
```

**JavaScript/TypeScript:**
```typescript
import { QuranAudio } from 'quran-audio';

const qa = new QuranAudio();
const url = qa.audioUrl('mishary_alafasi', { surah: 2, ayah: 255 });
const verse = await qa.verse('minshawy_murattal', { surah: 2, ayah: 255 });
```

**Implementation:** Wraps `sources` config (cached locally, refreshed periodically) + HF `/filter` API for timestamp access. No API keys needed.

### Web Component

A drop-in `<quran-verse>` element that any website can use. Handles audio fetching, playback, and word-level highlighting — zero backend required.

```html
<script src="https://unpkg.com/quran-audio-player"></script>

<!-- Minimal -->
<quran-verse surah="2" ayah="255"></quran-verse>

<!-- With options -->
<quran-verse
  surah="2" ayah="255"
  reciter="mishary_alafasi"
  highlight="word"
  show-translation="en">
</quran-verse>
```

**Features:**
- Audio playback with word-level karaoke highlighting (using `word_timestamps`)
- Reciter selection dropdown (populated from `sources` config)
- Responsive — works on mobile and desktop
- No backend — fetches audio from CDN, timestamps from HF `/filter` API
- Framework-agnostic (Web Components work in React, Vue, Angular, plain HTML)

### Cloudflare Worker Redirect

The lightest possible "API" — a URL rewriting layer that gives developers clean, stable URLs without us hosting audio. Runs on Cloudflare's free tier.

```
GET /v1/mishary_alafasi/2/255.mp3
→ 302 https://server8.mp3quran.net/afs/002.mp3  (for by_surah sources)

GET /v1/minshawy_murattal/2/255.mp3
→ 302 https://everyayah.com/data/Minshawy_Murattal_128kbps/002255.mp3  (for by_ayah sources)

GET /v1/mishary_alafasi/2.mp3
→ 302 https://server8.mp3quran.net/afs/002.mp3  (full chapter, gapless)
```

**Implementation:** Single Worker script (~100 lines) that loads URL templates from `sources` config (cached in KV store) and rewrites paths to CDN URLs. No audio storage, no bandwidth cost.

**Value:** Developers get a stable URL namespace (`/v1/{reciter}/{surah}/{ayah}.mp3`) that survives CDN URL changes. If mp3quran changes their URL structure, we update the templates — developer URLs stay the same.

---

## Browser & App Extensions

### Browser Extension (Chrome / Firefox)

**Concept:** Select Arabic Quranic text on any webpage → popup with audio playback and word highlighting.

**Features:**
- Right-click Arabic text → "Listen to this verse"
- Auto-detect surah:ayah from selected text (match against `qpc_hafs.json`)
- Popup player with reciter selection, word-level highlighting
- Optional: always-visible mini player for continuous listening

**Implementation:** Content script detects Arabic text, background script resolves verse reference and fetches audio URL from template. Medium effort.

### Obsidian / Notion Plugin

**Concept:** Embed verse audio inline in notes. Useful for scholars, students, and teachers.

```markdown
![[quran:2:255|mishary_alafasi]]
```

Renders as an inline audio player with text and timestamps.

---

## Broadcast Channels

### Daily Verse Bot (Telegram Channel / Discord Server / X)

Automated daily post with a verse, audio, and translation. Low effort, high visibility for the project.

### Podcast / RSS Feed

Auto-generated RSS feed with one episode per surah per reciter. Subscribable in any podcast app. The `sources` config + URL templates make this trivially generatable.

---

## Priority Assessment

| Channel | Impact | Effort | Dependency |
|---------|--------|--------|------------|
| **Client SDK (npm/PyPI)** | High — enables everything else | Low | `sources` config |
| **Web component** | High — zero-backend adoption | Medium | Client SDK |
| **Cloudflare Worker redirect** | Medium — stable URL namespace | Very low | `sources` config |
| **Telegram bot** | High — massive reach in target audience | Low | Client SDK or direct |
| **Discord bot** | Medium — developer communities | Low | Client SDK or direct |
| **Browser extension** | Medium — unique interaction model | Medium | Client SDK |
| **Daily verse bot** | Low-medium — visibility/marketing | Very low | URL templates |
| **Obsidian plugin** | Niche — scholars/students | Low-medium | Client SDK |
| **WhatsApp bot** | High reach, high effort | High | Business API approval |

**Recommended order:** SDK → Web component → Cloudflare redirect → Telegram bot → Discord bot → everything else as community contributions.

The SDK is the keystone — once it exists, bots and extensions become weekend projects for community contributors rather than core team work.
