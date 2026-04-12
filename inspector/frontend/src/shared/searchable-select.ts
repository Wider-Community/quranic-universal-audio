// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * SearchableSelect -- lightweight filterable wrapper around a native <select>.
 * Hides the <select>, shows a text input + dropdown overlay.
 * Fires native 'change' event on the hidden select so existing handlers work.
 */

/** Normalize Arabic text for fuzzy matching (private, not exported). */
function normalizeArabic(str) {
    return str
        .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]/g, '')
        .replace(/[أإآٱ]/g, 'ا')
        .replace(/ة/g, 'ه')
        .replace(/ى/g, 'ي');
}

export class SearchableSelect {
    constructor(selectEl) {
        this.select = selectEl;
        this.options = [];  // [{value, text, group}, ...]

        // Wrapper
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'ss-wrapper';
        selectEl.parentNode.insertBefore(this.wrapper, selectEl);
        this.wrapper.appendChild(selectEl);
        selectEl.style.display = 'none';

        // Text input
        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.className = 'ss-input';
        this.input.placeholder = '--';
        this.wrapper.appendChild(this.input);

        // Dropdown
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'ss-dropdown';
        this.dropdown.hidden = true;
        this.wrapper.appendChild(this.dropdown);

        this.highlightIdx = -1;
        this.filtered = [];

        this.input.addEventListener('focus', () => this._open());
        this.input.addEventListener('input', () => this._filter());
        this.input.addEventListener('keydown', e => this._onKey(e));
        document.addEventListener('click', e => {
            if (!this.wrapper.contains(e.target)) this._close();
        });

        this.refresh();
    }

    refresh() {
        this.options = [];
        for (const opt of this.select.options) {
            if (!opt.value) continue;  // skip placeholder
            const parent = opt.parentElement;
            const group = parent && parent.tagName === 'OPTGROUP' ? parent.label : '';
            this.options.push({ value: opt.value, text: opt.textContent, group });
        }
        // Sync displayed text to current select value
        const cur = this.select.value;
        const match = this.options.find(o => o.value === cur);
        this.input.value = match ? match.text : '';
        this._close();
    }

    _open() {
        this.input.value = '';
        this._filter();
        this.dropdown.hidden = false;
    }

    _close() {
        this.dropdown.hidden = true;
        this.highlightIdx = -1;
        // Restore display text to current selection
        const cur = this.select.value;
        const match = this.options.find(o => o.value === cur);
        this.input.value = match ? match.text : '';
    }

    _filter() {
        const q = normalizeArabic(this.input.value.toLowerCase());
        this.filtered = q
            ? this.options.filter(o =>
                normalizeArabic(o.text.toLowerCase()).includes(q) ||
                normalizeArabic(o.group.toLowerCase()).includes(q)
            )
            : [...this.options];
        this.highlightIdx = -1;
        this._render();
    }

    _render() {
        this.dropdown.innerHTML = '';
        let currentGroup = null;
        this.filtered.forEach((opt, i) => {
            if (opt.group && opt.group !== currentGroup) {
                currentGroup = opt.group;
                const header = document.createElement('div');
                header.className = 'ss-group-label';
                header.textContent = currentGroup;
                this.dropdown.appendChild(header);
            }

            const div = document.createElement('div');
            div.className = 'ss-option'
                + (opt.group ? ' ss-option-grouped' : '')
                + (i === this.highlightIdx ? ' ss-highlight' : '');
            div.textContent = opt.text;
            div.addEventListener('mousedown', e => { e.preventDefault(); this._pick(opt); });
            this.dropdown.appendChild(div);
        });
    }

    _pick(opt) {
        this.select.value = opt.value;
        this.input.value = opt.text;
        this._close();
        this.select.dispatchEvent(new Event('change'));
    }

    _onKey(e) {
        if (this.dropdown.hidden) {
            if (e.key === 'ArrowDown' || e.key === 'Enter') { this._open(); e.preventDefault(); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.highlightIdx = Math.min(this.highlightIdx + 1, this.filtered.length - 1);
            this._render();
            this._scrollToHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.highlightIdx = Math.max(this.highlightIdx - 1, 0);
            this._render();
            this._scrollToHighlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (this.highlightIdx >= 0 && this.highlightIdx < this.filtered.length) {
                this._pick(this.filtered[this.highlightIdx]);
            }
        } else if (e.key === 'Escape') {
            this._close();
        }
    }

    _scrollToHighlight() {
        const el = this.dropdown.querySelector('.ss-highlight');
        if (el) el.scrollIntoView({ block: 'nearest' });
    }
}
