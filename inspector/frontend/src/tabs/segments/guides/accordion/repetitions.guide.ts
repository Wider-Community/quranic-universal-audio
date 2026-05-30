const source = `
# Detected Repetitions

A repetition is the same text recited more than once because the model missed the silence, so it appears as a single segment instead of separate. Splitting it into the distinct passes — each with its own words — resolves it, and auto-split does most of the work. A few are false positives you can ignore.

> By the end this should be zero — resolved or ignored.

::example{id="reps_split_distinct"}
::example{id="reps_lookback"}
::example{id="reps_multiple"}
`;

export default source;
