# Inspector

Flask web app for reviewing and editing Quran recitation alignment results. Three tabs: **Timestamps** (waveform + karaoke phoneme display), **Segments** (browse/edit alignment output with validation), **Audio** (hierarchical recording browser).

## Setup

```bash
pip install flask
```

## Run

```bash
python inspector/server.py
```

Open http://localhost:5000.

## Keyboard shortcuts

### Timestamps tab

| Key | Action |
|-----|--------|
| Space | Play / pause |
| `[` / `]` | Previous / next verse |
| Left / Right | Seek ±3s |
| Up / Down | Previous / next word |
| `<` / `>` | Speed down / up |
| R | Random verse (same reciter) |
| Shift+R | Random verse (any reciter) |
| J | Scroll to active word |
| V | Toggle view mode |

### Segments tab

| Key | Action |
|-----|--------|
| Space | Play / pause |
| Left / Right | Seek ±3s |
| Up / Down | Previous / next segment |
| `<` / `>` | Speed down / up |
| S | Save (when dirty) |
| Ctrl+Z | Undo save |
| E | Edit reference |
| Enter | Confirm edit (in trim/split mode) |
| Escape | Exit edit mode |
| J | Scroll to active segment |
