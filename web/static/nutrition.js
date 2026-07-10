/**
 * Vitals OS — Nutrition dashboard Alpine controller.
 *
 * Same override flow as GLP-1/weight: 409 → confirm → re-POST with override=true.
 */

// Plain global function (not Alpine.data()/alpine:init) — x-data="nutritionDashboard()"
// calls this directly, so it works the instant this script runs. alpine:init fires
// once, on Alpine's initial boot; a boosted hx-boost navigation re-executes this
// <script> (it lives in <body>) long after that event already fired, so a listener
// registered here would silently never run, leaving nutritionDashboard undefined the
// first time this page is reached via SPA navigation instead of a hard reload.
window.nutritionDashboard = function () {
    return {
        overrideFlag: false,
        showConfirm: false,
        violations: [],
        lastFormEvent: null,
        isEditing: false,
        showForm: false,

        editMeal(meal) {
            this.isEditing = true;
            this.showForm = true;
            const form = document.getElementById('form-meal');
            if (!form) return;
            form.elements['date'].value = meal.date;
            form.elements['eaten_at'].value = meal.eaten_at || '';
            form.elements['name'].value = meal.name;
            form.elements['calories'].value = meal.calories ?? '';
            form.elements['protein_g'].value = meal.protein_g ?? '';
            form.elements['fat_g'].value = meal.fat_g ?? '';
            form.elements['carbs_g'].value = meal.carbs_g ?? '';
            form.elements['note'].value = meal.note || '';
            let idInput = form.querySelector('input[name="id"]');
            if (!idInput) {
                idInput = document.createElement('input');
                idInput.type = 'hidden';
                idInput.name = 'id';
                form.appendChild(idInput);
            }
            idInput.value = meal.id;
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.textContent = window.t('nutrition.update');
        },

        cancelEdit() {
            this.isEditing = false;
            const form = document.getElementById('form-meal');
            if (!form) return;
            form.reset();
            const idInput = form.querySelector('input[name="id"]');
            if (idInput) idInput.remove();
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.textContent = window.t('nutrition.save');
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
                    const redirectUrl = response.headers.get('HX-Redirect') || '/nutrition';
                    if (window.vitalsStashRestore) window.vitalsStashRestore({});
                    window.location.href = redirectUrl;
                } else {
                    restoreBtn();
                    if (window.vitalsToast) window.vitalsToast(window.t('save_error'));
                }
            } catch (err) {
                restoreBtn();
                if (window.vitalsToast) window.vitalsToast(window.t('network_error'));
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
    };
};
