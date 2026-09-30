/* The small behaviour of the server-rendered pages (sign-in, two-step code, 404). One file,
   no inline script, so the site's CSP can refuse inline script altogether. The words it
   shows come from data attributes the templates fill in the visitor's language. */
(function () {
    'use strict';

    /* Sign-in and two-step code: reveal the password, hold the button while it sends. */
    var form = document.querySelector('form.lg');
    if (form) {
        var submit = form.querySelector('[data-lg-submit]');
        var label = form.querySelector('[data-lg-submit-label]');
        var sending = form.getAttribute('data-sending');
        var password = form.querySelector('#lg-password');
        var code = form.querySelector('#lg-code');
        var reveal = form.querySelector('[data-lg-reveal]');

        if (form.querySelector('.lg-err')) {
            var field = password || code;
            if (field) field.focus();
        }

        if (reveal && password) {
            reveal.addEventListener('click', function () {
                var shown = password.type === 'text';
                password.type = shown ? 'password' : 'text';
                reveal.textContent = form.getAttribute(shown ? 'data-reveal' : 'data-hide');
                reveal.setAttribute('aria-pressed', String(!shown));
            });
        }

        /* The code is six digits: keep digits only, and send as soon as it is complete. */
        if (code) {
            code.addEventListener('input', function () {
                var digits = code.value.replace(/\D/g, '').slice(0, 6);
                if (digits !== code.value) code.value = digits;
                if (digits.length === 6) form.requestSubmit();
            });
        }

        form.addEventListener('submit', function () {
            if (!submit || submit.getAttribute('aria-busy') === 'true') return;
            submit.setAttribute('aria-busy', 'true');
            if (label && sending) label.textContent = sending;
        });
    }

    /* "Back" on the 404 page: the previous page, or the fallback when there is none. */
    var back = document.querySelector('[data-history-back]');
    if (back) {
        back.addEventListener('click', function () {
            if (history.length > 1) history.back();
            else location.assign(back.getAttribute('data-history-back') || '/');
        });
    }
})();
