/**
 * Parsed project-overview document — parsed once at module load and shared by
 * every consumer (the dashboard `InfoModal` for its title + body, and
 * `OverviewContent` for the rendered blocks). Edit wording in `overview.md`.
 */
import { parseInfoDoc } from './info-doc';
import OVERVIEW_MD from './overview.md?raw';

export const overviewDoc = parseInfoDoc(OVERVIEW_MD);
