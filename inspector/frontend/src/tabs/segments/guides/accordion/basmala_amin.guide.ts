const source = `
# Basmala + Amin

Three small, related cases: 

1. Basmala of Al-Fatiha: this is an ayah in Hafs so is kept, however, some sources use a generic basmala sound that does not belong to the reciter - in which case it should be deleted and results in a missing verse.

2. Amin in Al-Fatiha: if the recitation was during prayer, some of the Amin sound might be present and need trimming.

3. Basmala in other surahs: the pipeline already removes the basmala before non-Fatiha surahs since they are not verses, but occasionally this might be undetected — so first segment of surahs where there was no basmala deletions are flagged. This may be wrong so confirm, either remove the basmala from the segment or ignore.

> By the end this should be zero — resolved or ignored.

::example{id="basmala_nonfatiha"}
::example{id="basmala_added_voice"}
::example{id="amin_trim"}
`;

export default source;
