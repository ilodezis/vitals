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

        if (form.querySelector('.lg-err:not([hidden])')) {
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

        var passkey = form.querySelector('[data-passkey]');
        if (passkey && window.PublicKeyCredential && navigator.credentials) {
            passkeySignIn(form, passkey);
        }
    }

    /* Passkey sign-in: the button, and the username field's autofill (conditional
       mediation). Each attempt is one ceremony — options from the server, the browser's
       prompt, the signed answer back. The options are fetched before anyone taps, so the
       button opens the prompt inside the tap itself: Safari refuses a prompt that only
       arrives after a network round trip. */
    function passkeySignIn(form, button) {
        var buttonLabel = button.querySelector('[data-passkey-label]');
        var idleText = buttonLabel.textContent;
        var errorBox = form.querySelector('[data-passkey-error]');
        var errorText = form.querySelector('[data-passkey-error-text]');
        var nextField = form.querySelector('input[name="next"]');
        var options = null;      // the armed ceremony's options, ready for the browser
        var autofill = null;     // aborts the request listening in the autofill
        var refresh = null;
        var busy = false;
        var conditional = false;

        button.hidden = false;

        function toBuffer(value) {
            var base64 = value.replace(/-/g, '+').replace(/_/g, '/');
            var binary = atob(base64 + '==='.slice((base64.length + 3) % 4));
            var bytes = new Uint8Array(binary.length);
            for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            return bytes.buffer;
        }

        function toText(buffer) {
            var bytes = new Uint8Array(buffer);
            var binary = '';
            for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
            return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        }

        function setBusy(on) {
            busy = on;
            button.setAttribute('aria-busy', String(on));
            buttonLabel.textContent = on ? form.getAttribute('data-passkey-waiting') : idleText;
        }

        function showError(attribute) {
            var others = form.querySelectorAll('.lg-err:not([data-passkey-error])');
            for (var i = 0; i < others.length; i++) others[i].hidden = true;
            errorText.textContent = form.getAttribute(attribute);
            errorBox.hidden = false;
        }

        function stopListening() {
            if (autofill) autofill.abort();
            autofill = null;
        }

        /* A fresh ceremony from the server; where the browser can, offer the passkey in
           the username field's autofill straight away. */
        function arm() {
            options = null;
            stopListening();
            clearTimeout(refresh);
            return fetch('/login/passkey/options', { method: 'POST', credentials: 'same-origin' })
                .then(function (response) {
                    if (!response.ok) throw new Error('passkey options ' + response.status);
                    return response.json();
                })
                .then(function (json) {
                    json.challenge = toBuffer(json.challenge);
                    (json.allowCredentials || []).forEach(function (c) { c.id = toBuffer(c.id); });
                    options = json;
                    // The server forgets a challenge after five minutes.
                    refresh = setTimeout(rearm, 4 * 60 * 1000);
                    if (conditional && !busy) {
                        autofill = new AbortController();
                        navigator.credentials
                            .get({ publicKey: options, mediation: 'conditional', signal: autofill.signal })
                            .then(finish, function () { /* aborted, or dismissed */ });
                    }
                });
        }

        function rearm() {
            arm().catch(function () { /* the button retries on the next tap */ });
        }

        function prompt() {
            stopListening();
            setBusy(true);
            navigator.credentials.get({ publicKey: options }).then(finish, function (err) {
                setBusy(false);
                // NotAllowedError: the owner closed the sheet. Nothing to apologise for.
                if (!err || err.name !== 'NotAllowedError') showError('data-passkey-failed');
                rearm();
            });
        }

        function finish(credential) {
            stopListening();
            clearTimeout(refresh);
            setBusy(true);
            var response = credential.response;
            var body = {
                credential: {
                    id: credential.id,
                    rawId: toText(credential.rawId),
                    type: credential.type,
                    authenticatorAttachment: credential.authenticatorAttachment || undefined,
                    clientExtensionResults: credential.getClientExtensionResults(),
                    response: {
                        clientDataJSON: toText(response.clientDataJSON),
                        authenticatorData: toText(response.authenticatorData),
                        signature: toText(response.signature),
                        userHandle: response.userHandle ? toText(response.userHandle) : undefined
                    }
                },
                next: nextField ? nextField.value : '/'
            };
            fetch('/login/passkey/verify', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            })
                .then(function (r) {
                    return r.json().then(function (data) { return { ok: r.ok, data: data }; });
                })
                .then(function (result) {
                    if (result.ok && result.data.redirect) {
                        location.assign(result.data.redirect);
                        return;
                    }
                    if (result.data.error === 'unknown_credential') {
                        // Removed here, still on the phone: where the browser supports it,
                        // tell its keychain so it stops offering this one.
                        if (PublicKeyCredential.signalUnknownCredential && options) {
                            PublicKeyCredential.signalUnknownCredential({
                                rpId: options.rpId, credentialId: credential.id
                            }).catch(function () {});
                        }
                        showError('data-passkey-unknown');
                    } else {
                        showError('data-passkey-failed');
                    }
                    setBusy(false);
                    rearm();
                })
                .catch(function () {
                    showError('data-passkey-failed');
                    setBusy(false);
                    rearm();
                });
        }

        button.addEventListener('click', function () {
            if (busy) return;
            if (options) prompt();
            else arm().then(prompt, function () { showError('data-passkey-failed'); });
        });

        // A page brought back from the back/forward cache holds a stale challenge.
        window.addEventListener('pageshow', function (event) {
            if (event.persisted && !busy) rearm();
        });

        var check = PublicKeyCredential.isConditionalMediationAvailable;
        (check ? check.call(PublicKeyCredential) : Promise.resolve(false))
            .then(function (available) { conditional = !!available; }, function () {})
            .then(rearm);
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
