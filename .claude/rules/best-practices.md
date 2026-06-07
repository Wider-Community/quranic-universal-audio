# Best Practices

## Core Principles

### KISS (Keep It Simple)

- Prefer the simplest solution that actually works
- Avoid premature optimization
- Optimize for clarity over cleverness
- Do not overengineer or overabstract

### DRY (Don't Repeat Yourself)

- Extract repeated logic into shared functions or utilities
- Avoid copy-paste implementation drift
- Introduce abstractions when repetition is real, not speculative

### YAGNI (You Aren't Gonna Need It)

- Do not build features or abstractions before they are needed
- Avoid speculative generality

## File Organization

MANY SMALL FILES > FEW LARGE FILES:
- High cohesion, low coupling
- 100-400 lines good rule of thumb
- Extract utilities from large modules e.g. `lib/`, `utils/`, `helpers/`
- Organize by feature/domain, not by type

## Error Handling

ALWAYS handle errors comprehensively:
- Handle errors explicitly at every level
- Provide user-friendly error messages in UI-facing code
- Log detailed error context on the server side
- Never silently swallow errors

## Code Smells to Avoid

### Magic Numbers

Use named constants for meaningful thresholds, delays, and limits.

### Long Functions

Split large functions into focused pieces with clear responsibilities.

## Code Quality Checklist

Before marking work complete:
- [ ] Functions are small (<50 lines)
- [ ] Files are focused (<600 lines)
- [ ] No deep nesting (>5 levels)
- [ ] Proper error handling
- [ ] No hardcoded values (use constants or config)