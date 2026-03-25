/**
 * Audio Tab — browse and listen to full surah/ayah recitations.
 * Supports hierarchical audio sources: by_surah/<source> and by_ayah/<source>.
 * by_surah: Surah dropdown only.
 * by_ayah: Surah dropdown + Ayah dropdown with prev/next navigation.
 */

(function () {
    const reciterSelect = document.getElementById('aud-reciter-select');
    const surahSelect = document.getElementById('aud-surah-select');
    const ayahSelect = document.getElementById('aud-ayah-select');
    const ayahLabel = document.getElementById('aud-ayah-label');
    const player = document.getElementById('aud-player');
    const prevBtn = document.getElementById('aud-prev-btn');
    const nextBtn = document.getElementById('aud-next-btn');

    // State
    let currentCategory = null;  // derived from selected reciter
    let audioSources = {};
    // Cache: "category/source/slug" -> {key: url}
    const urlCache = {};
    // For by_ayah: parsed structure { surahNum -> [ayahNum, ...] } and flat sorted keys
    let ayahBySurah = {};   // { 1: [1,2,...,7], 2: [1,...,286], ... }
    let allSurahNums = [];  // sorted surah numbers available

    let audSurahSS = null;  // SearchableSelect for surah dropdown

    document.addEventListener('DOMContentLoaded', loadSources);

    async function loadSources() {
        try {
            await surahInfoReady;
            audSurahSS = new SearchableSelect(surahSelect);
            const res = await fetch('/api/audio/sources');
            audioSources = await res.json();
            populateReciters();
        } catch (e) {
            reciterSelect.innerHTML = '<option value="">Error loading sources</option>';
        }
    }

    function populateReciters() {
        reciterSelect.innerHTML = '<option value="">-- Select reciter --</option>';
        resetSurahSelect();
        resetAyahSelect();
        clearPlayer();

        for (const category of ['by_surah', 'by_ayah']) {
            const catData = audioSources[category];
            if (!catData) continue;

            for (const source of Object.keys(catData).sort()) {
                const reciters = catData[source];
                if (!reciters || reciters.length === 0) continue;

                const optgroup = document.createElement('optgroup');
                optgroup.label = `${category}/${source}`;
                for (const r of reciters) {
                    const opt = document.createElement('option');
                    opt.value = `${category}/${source}/${r.slug}`;
                    opt.textContent = r.name;
                    optgroup.appendChild(opt);
                }
                reciterSelect.appendChild(optgroup);
            }
        }

        ayahLabel.hidden = true;
        updateNavButtons();
    }

    reciterSelect.addEventListener('change', async () => {
        const val = reciterSelect.value;
        resetSurahSelect();
        resetAyahSelect();
        clearPlayer();

        if (!val) {
            currentCategory = null;
            ayahLabel.hidden = true;
            return;
        }

        // val is "category/source/slug"
        const parts = val.split('/');
        currentCategory = parts[0];
        const sourceSlug = parts.slice(1).join('/');  // "source/slug"

        // Show/hide ayah dropdown based on category
        ayahLabel.hidden = currentCategory !== 'by_ayah';

        const cacheKey = val;

        try {
            let urls = urlCache[cacheKey];
            if (!urls) {
                const res = await fetch(`/api/audio/surahs/${currentCategory}/${sourceSlug}`);
                const data = await res.json();
                urls = data.surahs || {};
                urlCache[cacheKey] = urls;
            }

            if (currentCategory === 'by_ayah') {
                buildAyahStructure(urls);
                populateSurahSelect(allSurahNums);
            } else {
                const nums = Object.keys(urls).map(Number).sort((a, b) => a - b);
                populateSurahSelect(nums);
            }
        } catch (e) {
            surahSelect.innerHTML = '<option value="">Error loading</option>';
        }
    });

    surahSelect.addEventListener('change', () => {
        if (currentCategory === 'by_ayah') {
            populateAyahSelect();
            clearPlayer();
        } else {
            playCurrentSelection();
        }
        updateNavButtons();
    });

    ayahSelect.addEventListener('change', () => {
        playCurrentSelection();
        updateNavButtons();
    });

    prevBtn.addEventListener('click', () => navigate(-1));
    nextBtn.addEventListener('click', () => navigate(+1));

    // -- Helpers --

    function buildAyahStructure(urls) {
        ayahBySurah = {};
        for (const key of Object.keys(urls)) {
            const parts = key.split(':');
            const s = Number(parts[0]);
            const a = Number(parts[1]);
            if (!ayahBySurah[s]) ayahBySurah[s] = [];
            ayahBySurah[s].push(a);
        }
        for (const s of Object.keys(ayahBySurah)) {
            ayahBySurah[s].sort((a, b) => a - b);
        }
        allSurahNums = Object.keys(ayahBySurah).map(Number).sort((a, b) => a - b);
    }

    function populateSurahSelect(nums) {
        surahSelect.innerHTML = '<option value="">-- Select --</option>';
        for (const n of nums) {
            const opt = document.createElement('option');
            opt.value = n;
            opt.textContent = surahOptionText(n);
            surahSelect.appendChild(opt);
        }
        if (audSurahSS) audSurahSS.refresh();
    }

    function populateAyahSelect() {
        resetAyahSelect();
        const s = Number(surahSelect.value);
        if (!s || !ayahBySurah[s]) return;

        ayahSelect.innerHTML = '<option value="">-- Select --</option>';
        for (const a of ayahBySurah[s]) {
            const opt = document.createElement('option');
            opt.value = a;
            opt.textContent = a;
            ayahSelect.appendChild(opt);
        }
    }

    function playCurrentSelection() {
        const val = reciterSelect.value;
        if (!val) { clearPlayer(); return; }

        const urls = urlCache[val];
        if (!urls) { clearPlayer(); return; }

        let key;
        if (currentCategory === 'by_ayah') {
            const s = surahSelect.value;
            const a = ayahSelect.value;
            if (!s || !a) { clearPlayer(); return; }
            key = `${s}:${a}`;
        } else {
            key = surahSelect.value;
            if (!key) { clearPlayer(); return; }
        }

        const url = urls[key];
        if (url) {
            player.src = url;
            player.load();
        } else {
            clearPlayer();
        }
    }

    function navigate(delta) {
        if (currentCategory === 'by_ayah') {
            navigateAyah(delta);
        } else {
            const newIdx = surahSelect.selectedIndex + delta;
            if (newIdx < 1 || newIdx >= surahSelect.options.length) return;
            surahSelect.selectedIndex = newIdx;
            if (audSurahSS) audSurahSS.refresh();
            playCurrentSelection();
            updateNavButtons();
        }
    }

    function navigateAyah(delta) {
        const s = Number(surahSelect.value);
        const a = Number(ayahSelect.value);
        if (!s || !a) return;

        const ayahs = ayahBySurah[s];
        const idx = ayahs.indexOf(a);
        const newIdx = idx + delta;

        if (newIdx >= 0 && newIdx < ayahs.length) {
            // Move within same surah
            ayahSelect.selectedIndex = newIdx + 1; // +1 for placeholder
        } else if (delta > 0) {
            // Move to first ayah of next surah
            const sIdx = allSurahNums.indexOf(s);
            if (sIdx >= allSurahNums.length - 1) return;
            const nextS = allSurahNums[sIdx + 1];
            surahSelect.value = nextS;
            if (audSurahSS) audSurahSS.refresh();
            populateAyahSelect();
            ayahSelect.selectedIndex = 1; // first ayah after placeholder
        } else {
            // Move to last ayah of previous surah
            const sIdx = allSurahNums.indexOf(s);
            if (sIdx <= 0) return;
            const prevS = allSurahNums[sIdx - 1];
            surahSelect.value = prevS;
            if (audSurahSS) audSurahSS.refresh();
            populateAyahSelect();
            ayahSelect.selectedIndex = ayahSelect.options.length - 1; // last ayah
        }
        playCurrentSelection();
        updateNavButtons();
    }

    function updateNavButtons() {
        if (currentCategory === 'by_ayah') {
            const s = Number(surahSelect.value);
            const a = Number(ayahSelect.value);
            if (!s || !a) {
                prevBtn.disabled = true;
                nextBtn.disabled = true;
                return;
            }
            const ayahs = ayahBySurah[s];
            const aIdx = ayahs.indexOf(a);
            const sIdx = allSurahNums.indexOf(s);
            prevBtn.disabled = (sIdx === 0 && aIdx === 0);
            nextBtn.disabled = (sIdx === allSurahNums.length - 1 && aIdx === ayahs.length - 1);
        } else {
            const idx = surahSelect.selectedIndex;
            const len = surahSelect.options.length;
            prevBtn.disabled = (idx <= 1);
            nextBtn.disabled = (idx < 1 || idx >= len - 1);
        }
    }

    function resetSurahSelect() {
        surahSelect.innerHTML = '<option value="">--</option>';
        ayahBySurah = {};
        allSurahNums = [];
        if (audSurahSS) audSurahSS.refresh();
    }

    function resetAyahSelect() {
        ayahSelect.innerHTML = '<option value="">--</option>';
    }

    function clearPlayer() {
        player.removeAttribute('src');
        player.load();
        updateNavButtons();
    }
})();
