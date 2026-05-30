// The project-overview guide — the FIRST required reading in the first-edit
// gate. Like the editing guide, it isn't tied to a validation category: its
// body is the shared `OverviewContent` (lifecycle pills + links), mounted by
// AccordionGuideModal via the `::component` directive. The H1 supplies the
// title in both the gate list and the modal header — keep it in sync with the
// dashboard InfoModal title (the `overview.md` H1).
const source = `
# About Qur'anic Universal Audio

::component{name="overview"}
`;

export default source;
