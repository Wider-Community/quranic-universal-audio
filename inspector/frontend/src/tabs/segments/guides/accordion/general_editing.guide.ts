// The general editing guide is the one required guide that is NOT tied to a
// validation category. Its body is hand-authored, illustrated Svelte (annotated
// mock cards), so the source is just the H1 (which supplies the title in both
// the gate list and the modal header) plus a single `::component` directive
// that mounts `EditingGuideContent` via AccordionGuideModal's GUIDE_COMPONENTS.
const source = `
# Editing guide

::component{name="editing-guide"}
`;

export default source;
