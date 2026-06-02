const source = `
# Failed Alignments

A failed alignment is an audio segment the model couldn't resolve.

- Sometimes the recitation is fine and the model is simply wrong — fix it. 

- Other times the failure is real e.g. non-Quranic audio, or a defect. It should be deleted.

- Occasionaly, a non-failed segment that is a slip, stutter, or audio issue has text that does not match the audio. In this case, we intentionally mark it as failed on purpose by entering an empty reference. It then drops out of the published timestamps, the verse still reconstructs cleanly, and anyone viewing the reciter can see at a glance that it was an audio or recitation issue — not a gap in the pipeline.

> By the end of a review this should reach zero — unless some were failed intentionally, in which case it stays above zero by design.

## The model was wrong — fix it

::example{id="failed_remerge_madd"}
::example{id="failed_remerge_start"}
::example{id="failed_recover_word"}

## Non-Quranic audio — delete it

::example{id="failed_nonquran_takbir"}
::example{id="failed_nonquran_speech"}
::example{id="failed_nonquran_speech2"}

## A clean version exists — mark it failed on purpose

::example{id="failed_intentional_dup"}
::example{id="failed_intentional_retry"}
::example{id="failed_intentional_split"}
`;

export default source;
