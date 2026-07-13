/**
 * Vitals OS — generic conflict-aware form controller (supplements / skincare).
 *
 * Reuses the weight/glp1 override pattern: POST via fetch, on 409 show the
 * violations modal, "save anyway" re-POSTs with override=true. Also a generic
 * row editor that fills a form's fields from a plain object.
 *
 * NOTE: x-data="protocolForm()" — called directly as a global function.
 * showFormModal is included in the returned object so no spread is needed.
 * This avoids dependency on Alpine.data() / alpine:init registration order.
 */

window.protocolForm = function() {
    return {
        overrideFlag: false,
        showConfirm: false,
        showFormModal: false,
        violations: [],
        lastFormEvent: null,
        isEditing: false,

        async submitForm(e) {
            this.lastFormEvent = e;
            const form = e.target;
            // Block double-submit. Relabel only text buttons; icon-only buttons
            // (e.g. archive toggle) are just disabled so their SVG stays intact.
            const btn = form.querySelector('button[type="submit"]');
            const isTextBtn = btn && !btn.querySelector('svg');
            const prevLabel = btn ? btn.textContent : null;
            if (btn) { btn.disabled = true; if (isTextBtn) btn.textContent = window.t('saving'); }
            const restoreBtn = () => {
                if (btn) { btn.disabled = false; if (isTextBtn && prevLabel !== null) btn.textContent = prevLabel; }
            };

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
                    const redirectUrl = response.headers.get('HX-Redirect') || window.location.pathname;
                    if (window.vitalsStashRestore) window.vitalsStashRestore({});
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
        },

        // Fill a form's named fields from `obj`; ensures a hidden `id` input.
        editRow(formId, obj, submitLabel) {
            this.isEditing = true;
            const form = document.getElementById(formId);
            if (!form) return;
            Object.keys(obj).forEach(name => {
                const el = form.elements[name];
                if (!el) return;

                if (el instanceof HTMLCollection || el instanceof NodeList || (el.type === undefined && el.length > 0)) {
                    const values = Array.isArray(obj[name]) ? obj[name] : [];
                    Array.from(el).forEach(input => {
                        if (input.type === 'checkbox') {
                            input.checked = values.includes(Number(input.value)) || values.includes(input.value) || values.includes(String(input.value));
                        }
                    });
                } else if (el.type === 'checkbox') {
                    el.checked = !!obj[name];
                } else {
                    el.value = obj[name] === null || obj[name] === undefined ? '' : obj[name];
                }
            });
            let idInput = form.querySelector('input[name="id"]');
            if (!idInput) {
                idInput = document.createElement('input');
                idInput.type = 'hidden';
                idInput.name = 'id';
                form.appendChild(idInput);
            }
            idInput.value = obj.id;
            const btn = form.querySelector('button[type="submit"]');
            if (btn && submitLabel) btn.textContent = submitLabel;
            try { form.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) {}
        },

        cancelEdit(formId, submitLabel) {
            this.isEditing = false;
            const form = document.getElementById(formId);
            if (!form) {
                return;
            }
            form.reset();
            const idInput = form.querySelector('input[name="id"]');
            if (idInput) idInput.remove();
            const btn = form.querySelector('button[type="submit"]');
            if (btn && submitLabel) btn.textContent = submitLabel;
        }
    };
};

// Register with Alpine.data as well (for named component syntax), via both
// alpine:init (deferred Alpine) and direct registration if Alpine is already loaded.
function _registerProtocolForm() {
    if (window.Alpine && window.Alpine.data) {
        window.Alpine.data('protocolForm', window.protocolForm);
    }
}
document.addEventListener('alpine:init', _registerProtocolForm);
// Also try immediately in case Alpine already started (e.g. non-defer builds)
if (document.readyState !== 'loading') {
    _registerProtocolForm();
} else {
    document.addEventListener('DOMContentLoaded', _registerProtocolForm);
}
