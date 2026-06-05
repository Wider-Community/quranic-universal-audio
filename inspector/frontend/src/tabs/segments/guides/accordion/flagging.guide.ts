// The flagging guide teaches the manual "needs a second look" flag — not a
// validation category. Its body is hand-authored, illustrated Svelte (a mock
// card plus a mock comment thread), so the source is the H1 (which supplies the
// modal title + the gate-list title), one line of intent, a short prose
// paragraph on the thread mechanics, and the `::component` directive that mounts
// `FlaggingGuideContent` via AccordionGuideModal's GUIDE_COMPONENTS.
const source = `
# Flagging

Flag any issue for weird cases or when unsure.

::component{name="flagging-demo"}
`;

export default source;
