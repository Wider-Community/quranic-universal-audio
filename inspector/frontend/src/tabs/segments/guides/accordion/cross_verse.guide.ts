const source = `
# Cross-verse

A cross-verse segment spans a verse boundary. We split it because the published dataset stores one row per verse, so each verse can be searched and played on its own. How you split depends on what the reciter did, and the boundary tag is kept as metadata either way.

> By the end this should be zero — all split. Auto-split usually is mostly accurate, but cursors might need some adjusting in some cases, especially in Wasl.

## Waqf — the reciter paused

The reciter stopped at the boundary but the model missed the silence. Split at the pause.

::example{id="xverse_waqf"}
::example{id="xverse_multi"}

## Wasl — the reciter continued

There's no silence to cut. Split where the two verses separate most cleanly and tag the boundary wasl, so the data records that the reciter ran them together.

::example{id="xverse_wasl"}
`;

export default source;
