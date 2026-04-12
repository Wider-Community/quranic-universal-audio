// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Audio Tab -- browse and listen to full surah/ayah recitations.
 * Supports hierarchical audio sources: by_surah/<source> and by_ayah/<source>.
 * by_surah: Surah dropdown only.
 * by_ayah: Surah dropdown + Ayah dropdown with prev/next navigation.
 */

import { SearchableSelect } from '../shared/searchable-select';
import { surahInfoReady, surahOptionText } from '../shared/surah-info';
import { LS_KEYS } from '../shared/constants';

const categoryToggle = document.getElementById('aud-category-toggle');
const reciterSelect = document.getElementById('aud-reciter-select');
const surahSelect = document.getElementById('aud-surah-select');
const ayahSelect = document.getElementById('aud-ayah-select');
const ayahLabel = document.getElementById('aud-ayah-label');
const player = document.getElementById('aud-player');
const prevBtn = document.getElementById('aud-prev-btn');
const nextBtn = document.getElementById('aud-next-btn');

// State
let selectedCategory = 'by_surah';  // driven by toggle
let currentCategory = null;  // derived from selected reciter (may differ until reciter chosen)
let audioSources = {};
// Cache: "category/source/slug" -> {key: url}
const urlCache = {};
// For by_ayah: parsed structure { surahNum -> [ayahNum, ...] } and flat sorted keys
let ayahBySurah = {};   // { 1: [1,2,...,7], 2: [1,...,286], ... }
let allSurahNums = [];  // sorted surah numbers available

let audReciterSS = null;  // SearchableSelect for reciter dropdown
let audSurahSS = null;  // SearchableSelect for surah dropdown

categoryToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cat]');
    if (!btn) return;
    const cat = btn.dataset.cat;
    if (cat === selectedCategory) return;
    selectedCategory = cat;
    categoryToggle.querySelectorAll('.ts-view-btn').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
    ayahLabel.hidden = (selectedCategory !== 'by_ayah');
    populateReciters();
});

document.addEventListener('DOMContentLoaded', loadSources);

async function loadSources() {
    try {
        await surahInfoReady;
        audReciterSS = new SearchableSelect(reciterSelect);
        audSurahSS = new SearchableSelect(surahSelect);
        const res = await fetch('/api/audio/sources');
        audioSources = await res.json();

        // Restore category from saved reciter before populating
        const _savedAudReciter = localStorage.getItem(LS_KEYS.AUD_RECITER);
        if (_savedAudReciter) {
            const _savedCat = _savedAudReciter.split('/')[0];
            if ((_savedCat === 'by_surah' || _savedCat === 'by_ayah') && _savedCat !== selectedCategory) {
                selectedCategory = _savedCat;
                categoryToggle.querySelectorAll('[data-cat]').forEach(b => b.classList.toggle('active', b.dataset.cat === selectedCategory));
                ayahLabel.hidden = (selectedCategory !== 'by_ayah');
            }
        }

        populateReciters();
    } catch (e) {
        reciterSelect.innerHTML = '<option value="">Error loading sources</option>';
        if (audReciterSS) audReciterSS.refresh();
    }
}

function populateReciters() {
    reciterSelect.innerHTML = '<option value="">-- Select reciter --</option>';
    resetSurahSelect();
    resetAyahSelect();
    clearPlayer();
    currentCategory = null;

    const catData = audioSources[selectedCategory];
    if (catData) {
        for (const source of Object.keys(catData).sort()) {
            const reciters = catData[source];
            if (!reciters || reciters.length === 0) continue;

            const optgroup = document.createElement('optgroup');
            optgroup.label = source;
            for (const r of reciters) {
                const opt = document.createElement('option');
                opt.value = `${selectedCategory}/${source}/${r.slug}`;
                opt.textContent = r.name;
                optgroup.appendChild(opt);
            }
            reciterSelect.appendChild(optgroup);
        }
    }

    if (audReciterSS) audReciterSS.refresh();
    ayahLabel.hidden = (selectedCategory !== 'by_ayah');
    updateNavButtons();

    // Restore saved reciter (only when this is the category the user last used)
    const _savedAudReciter = localStorage.getItem(LS_KEYS.AUD_RECITER);
    if (_savedAudReciter && _savedAudReciter.startsWith(selectedCategory + '/')) {
        reciterSelect.value = _savedAudReciter;
        if (reciterSelect.value === _savedAudReciter) {
            if (audReciterSS) audReciterSS.refresh(); // sync SS input display
            reciterSelect.dispatchEvent(new Event('change'));
        }
    }
}

reciterSelect.addEventListener('change', async () => {
    const val = reciterSelect.value;
    if (val) localStorage.setItem(LS_KEYS.AUD_RECITER, val);
    resetSurahSelect();
    resetAyahSelect();
    clearPlayer();

    if (!val) {
        currentCategory = null;
        return;
    }

    // val is "category/source/slug"
    const parts = val.split('/');
    currentCategory = parts[0];
    const sourceSlug = parts.slice(1).join('/');  // "source/slug"

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
