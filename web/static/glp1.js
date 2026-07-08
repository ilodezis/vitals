/**
 * Vitals OS — GLP-1 dashboard Alpine controller.
 *
 * Mirrors the weight dashboard's override flow (409 → confirm → re-POST with
 * override=true) and adds body-map site selection + injection edit.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('glp1Dashboard', (lastSite) => ({
        activeTab: 'injection',
        overrideFlag: false,
        showConfirm: false,
        violations: [],
        lastFormEvent: null,
        isEditing: false,
        showForm: false,
        // Pre-select the last-used site so rotation away from it is one tap.
        selectedSite: lastSite || null,

        // U9: restore the tab a save redirected away from (see vitalsStashRestore
        // in base.html <head> — must read this in init(), not later, since
        // window.load fires after Alpine has already built this component).
        init() {
            if (window.__vitalsRestoreTab) {
                this.activeTab = window.__vitalsRestoreTab;
                window.__vitalsRestoreTab = null;
            }
        },

        editInjection(inj) {
            this.activeTab = 'injection';
            this.isEditing = true;
            this.showForm = true;
            this.selectedSite = inj.site || null;
            const form = document.getElementById('form-injection');
            if (!form) return;
            form.elements['date'].value = inj.date;
            form.elements['drug'].value = inj.drug;
            form.elements['dose_mg'].value = inj.dose_mg;
            form.elements['note'].value = inj.note || '';
            let idInput = form.querySelector('input[name="id"]');
            if (!idInput) {
                idInput = document.createElement('input');
                idInput.type = 'hidden';
                idInput.name = 'id';
                form.appendChild(idInput);
            }
            idInput.value = inj.id;
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.textContent = window.t('glp1.update');
        },

        cancelEdit() {
            this.isEditing = false;
            this.selectedSite = null;
            const form = document.getElementById('form-injection');
            if (!form) return;
            form.reset();
            const idInput = form.querySelector('input[name="id"]');
            if (idInput) idInput.remove();
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.textContent = window.t('glp1.save');
        },

        async submitForm(e) {
            this.lastFormEvent = e;
            const form = e.target;
            const btn = form.querySelector('button[type="submit"]');
            const prevLabel = btn ? btn.textContent : null;
            if (btn) { btn.disabled = true; btn.textContent = window.t('saving'); }
            const restoreBtn = () => { if (btn) { btn.disabled = false; if (prevLabel !== null) btn.textContent = prevLabel; } };

            const formData = new FormData(form);
            formData.set('override', this.overrideFlag ? 'true' : 'false');

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    headers: { 'hx-request': 'true' }
                });

                if (response.status === 409) {
                    const data = await response.json();
                    this.violations = data.violations;
                    this.showConfirm = true;
                    restoreBtn();
                } else if (response.ok) {
                    const redirectUrl = response.headers.get('HX-Redirect') || '/glp1';
                    if (window.vitalsStashRestore) window.vitalsStashRestore({ tab: this.activeTab });
                    window.location.href = redirectUrl;
                } else {
                    restoreBtn();
                    if (window.vitalsToast) window.vitalsToast(window.t('save_error'));
                    console.error('Submission failed:', response.statusText);
                }
            } catch (err) {
                restoreBtn();
                if (window.vitalsToast) window.vitalsToast(window.t('network_error'));
                console.error('Request error:', err);
            }
        },

        overrideSave() {
            this.overrideFlag = true;
            this.showConfirm = false;
            if (this.lastFormEvent) this.submitForm(this.lastFormEvent);
        },

        cancelOverride() {
            this.showConfirm = false;
            this.overrideFlag = false;
            this.violations = [];
            this.lastFormEvent = null;
        }
    }));
});
