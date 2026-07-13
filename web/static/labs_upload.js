/**
 * Labs module — upload -> preview -> confirm queue.
 *
 * Mirrors the body-scan flow in app.js (bsUpload/bsSave): a file is recognized
 * server-side, then shown back for the owner to edit before anything is saved.
 * Labs differs in one way — a lab visit sometimes produces more than one
 * document — so this controller lets the user pick several files at once but
 * still uploads/previews/confirms them one at a time (one upload = one
 * raw_payload = one preview), advancing automatically after each save/skip
 * until the queue is empty. That keeps the batch-selection UX while giving
 * every document its own edit-before-save step.
 *
 * Plain global function (not Alpine.data()/alpine:init), loaded once from
 * <head> — see the comment above the page-controller <script> block in
 * base.html for why.
 */
window.labsUpload = function (showUploadInitial) {
    return {
        // ── Existing page toggles (previously an inline x-data object) ───────
        showUpload: !!showUploadInitial,
        showOnlyProblematic: false,

        // ── Upload queue ──────────────────────────────────────────────────────
        lqQueue: [],
        lqTotal: 0,
        lqIndex: 0,
        lqUploading: false,
        lqSaving: false,
        lqPreviewOpen: false,
        lqFailed: 0,
        lqConfirmed: 0,
        lqLab: { date: '', lab_name: '', file_key: null, raw_payload_id: null },
        lqRows: [],

        async lqSubmit(e) {
            const form = e.target;
            const fileInput = form.querySelector('input[type="file"]');
            this.lqQueue = Array.from(fileInput.files);
            this.lqTotal = this.lqQueue.length;
            this.lqIndex = 0;
            this.lqFailed = 0;
            this.lqConfirmed = 0;
            form.reset();
            const hint = form.querySelector('.v-file-drop__hint');
            if (hint && hint.dataset.default) hint.textContent = hint.dataset.default;
            await this._lqProcessNext();
        },

        async _lqProcessNext() {
            if (!this.lqQueue.length) {
                this._lqFinish();
                return;
            }
            const file = this.lqQueue.shift();
            this.lqIndex += 1;
            this.lqUploading = true;
            if (window.vitalsLoader) {
                window.vitalsLoader.show(window.t('loader.labs_upload_title'), window.t('loader.labs_upload_text'));
            }
            const fd = new FormData();
            fd.append('file', file);
            try {
                const resp = await fetch('/labs/upload', {
                    method: 'POST', body: fd, headers: { 'hx-request': 'true' }
                });
                const data = await resp.json();
                if (!resp.ok || !data.ok) {
                    // Not-configured applies to every file in the queue identically —
                    // stop immediately rather than burning through the rest, unless
                    // earlier files already saved (then a plain failure tally reads
                    // better than abandoning the summary banner mid-queue).
                    if (data && data.reason === 'not_configured' && this.lqConfirmed === 0 && this.lqFailed === 0) {
                        window.location.href = '/labs?upload=not_configured';
                        return;
                    }
                    this.lqFailed += 1;
                    await this._lqProcessNext();
                    return;
                }
                this.lqLab = {
                    date: data.lab.date,
                    lab_name: data.lab.lab_name || '',
                    file_key: data.lab.file_key,
                    raw_payload_id: data.lab.raw_payload_id
                };
                this.lqRows = (data.lab.markers || []).map(r => ({ ...r }));
                this.lqPreviewOpen = true;
            } catch (err) {
                this.lqFailed += 1;
                await this._lqProcessNext();
            } finally {
                this.lqUploading = false;
                if (window.vitalsLoader) window.vitalsLoader.hide();
            }
        },

        lqAddRow() {
            this.lqRows.push({ marker: '', value: null, unit: '', ref_low: null, ref_high: null });
        },
        lqRemoveRow(i) { this.lqRows.splice(i, 1); },

        // Discard this file's recognized rows without saving (raw upload stays in
        // the data-lake, unprocessed) and move on to the next queued file.
        lqSkip() {
            this.lqPreviewOpen = false;
            this.lqRows = [];
            this._lqProcessNext();
        },

        async lqSave() {
            if (this.lqSaving) return;
            this.lqSaving = true;
            const rows = this.lqRows.filter(r => r.value !== null && r.value !== '' && r.marker);
            const payload = {
                date: this.lqLab.date,
                lab_name: this.lqLab.lab_name || null,
                file_key: this.lqLab.file_key,
                raw_payload_id: this.lqLab.raw_payload_id,
                markers: rows
            };
            try {
                const resp = await fetch('/labs/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'hx-request': 'true' },
                    body: JSON.stringify(payload)
                });
                if (resp.ok) {
                    const data = await resp.json();
                    // "added" in the summary banner counts markers (matching
                    // labs.upload_ok's "{count} marker(s)"), not files/confirms —
                    // one file's preview can hold several markers.
                    this.lqConfirmed += (data && data.created) || 0;
                    this.lqPreviewOpen = false;
                    this.lqRows = [];
                    await this._lqProcessNext();
                } else if (window.vitalsToast) {
                    window.vitalsToast(window.t('save_error'));
                }
            } catch (err) {
                if (window.vitalsToast) window.vitalsToast(window.t('network_error'));
            } finally {
                this.lqSaving = false;
            }
        },

        // Whole queue is done: land on the same summary banner the old
        // server-side batch upload used (?upload=ok&added=N&failed=M), or do
        // nothing if the user skipped every file.
        _lqFinish() {
            if (this.lqConfirmed > 0 || this.lqFailed > 0) {
                const qs = new URLSearchParams({ upload: 'ok', added: this.lqConfirmed, failed: this.lqFailed });
                window.location.href = '/labs?' + qs.toString();
            }
        },

        lqProgressLabel() {
            return window.t('labs.queue_progress').replace('{index}', this.lqIndex).replace('{total}', this.lqTotal);
        }
    };
};
