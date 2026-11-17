/* ============================================================
   SPARC 2026 - Ambassador form behaviours
   1. IEEE fields show/hide (PDF: fields 13-16 only if member = Yes)
   2. Live 50-word bio counter; submit blocked while over the limit
   3. Photo pre-check: JPG/PNG only, max 10 MB (client-side; the
      server re-checks everything in Phase 3)
   4. AJAX submit with loading state; renders the exact PDF
      confirmation message on success; falls back to a normal
      browser submit if the server does not answer with JSON
      (the JSON contract {success, message, errors} is fixed in Phase 3)
   ============================================================ */
(function () {
  'use strict';

  var form = document.getElementById('ambassador-form');
  if (!form) return;

  var ieeeFields = document.getElementById('ieee-fields');
  var bio = document.getElementById('id_bio');
  var counter = document.getElementById('bio-counter');
  var photo = document.getElementById('id_photo');
  var photoError = document.getElementById('photo-error');
  var submitBtn = document.getElementById('submit-btn');
  var MAX_WORDS = counter ? parseInt(counter.getAttribute('data-max'), 10) || 50 : 50;
  var MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB, per the PDF

  /* ---------- 1. IEEE toggle ---------- */

  function syncIeee() {
    if (!ieeeFields) return;
    var chosen = form.querySelector('input[name="is_ieee_member"]:checked');
    var isMember = !!chosen && chosen.value === 'True';
    ieeeFields.hidden = !isMember;
    // Disabled fields are skipped by the browser and by screen readers,
    // and they are simply absent from FormData - which matches the
    // server rule "required only when the applicant is a member".
    var els = ieeeFields.querySelectorAll('input, select, textarea');
    for (var i = 0; i < els.length; i++) els[i].disabled = !isMember;
  }

  var ieeeRadios = form.querySelectorAll('input[name="is_ieee_member"]');
  for (var i = 0; i < ieeeRadios.length; i++) {
    ieeeRadios[i].addEventListener('change', syncIeee);
  }
  syncIeee();

  /* ---------- 2. Bio word counter ---------- */

  function countWords(text) {
    var words = text.trim().split(/\s+/);
    return words.length === 1 && words[0] === '' ? 0 : words.length;
  }

  function syncCounter() {
    if (!bio || !counter) return;
    var n = countWords(bio.value);
    if (n > MAX_WORDS) {
      counter.textContent = n + ' / ' + MAX_WORDS + ' words - trim to ' + MAX_WORDS + ' to submit';
      counter.className = 'word-counter over';
      form.setAttribute('data-bio-over', 'true');
    } else {
      counter.textContent = n + ' / ' + MAX_WORDS + ' words';
      counter.className = 'word-counter' + (n > MAX_WORDS - 5 ? ' near' : '');
      form.removeAttribute('data-bio-over');
    }
  }

  if (bio) {
    bio.addEventListener('input', syncCounter);
    syncCounter();
  }

  /* ---------- 3. Photo pre-check ---------- */

  function showPhotoError(message) {
    if (!photoError) return;
    photoError.textContent = message;
    photoError.hidden = false;
    if (photo) photo.value = ''; // drop the rejected file
  }

  function syncPhoto() {
    if (!photo || !photoError) return;
    photoError.hidden = true;
    photoError.textContent = '';
    var f = photo.files && photo.files[0];
    if (!f) return;
    var typeOk = /^image\/(jpe?g|png)$/i.test(f.type);
    var nameOk = /\.(jpe?g|png)$/i.test(f.name);
    if (!(typeOk && nameOk)) {
      showPhotoError('Please upload a JPG or PNG image.');
    } else if (f.size > MAX_FILE_BYTES) {
      showPhotoError('Photo is too large (' + (f.size / 1048576).toFixed(1) +
                     ' MB). Maximum is 10 MB.');
    }
  }

  if (photo) photo.addEventListener('change', syncPhoto);

  /* ---------- 4. Submit: guard, AJAX, confirmation, fallback ---------- */

  function setBusy(busy) {
    if (!submitBtn) return;
    submitBtn.disabled = busy;
    submitBtn.textContent = busy ? 'Submitting...' : 'Submit application';
  }

  function csrfToken() {
    var el = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
  }

  function nativeSubmit() {
    form.setAttribute('data-native-submit', 'true');
    form.submit(); // normal browser POST (page reloads)
  }

  function showConfirmation() {
    var box = document.getElementById('confirmation');
    form.hidden = true;
    var head = document.querySelector('.form-head');
    if (head) head.hidden = true;
    if (box) {
      box.hidden = false;
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      window.location.href = '/thanks/';
    }
  }

  function renderErrors(errors) {
    // Contract (Phase 3): { fieldName: ["message", ...], ... }
    var lists = form.querySelectorAll('.errorlist');
    for (var i = 0; i < lists.length; i++) {
      if (lists[i].hasAttribute('data-server')) continue; // keep server-rendered ones
      lists[i].parentNode.removeChild(lists[i]);
    }
    var first = null;
    for (var name in errors) {
      if (!Object.prototype.hasOwnProperty.call(errors, name)) continue;
      var host = form.querySelector('[data-field="' + name + '"]');
      if (!host) {
        if (name === '__all__') {
          host = form.querySelector('.submit-row') || form;
        } else {
          continue;
        }
      }
      var ul = document.createElement('ul');
      ul.className = 'errorlist';
      for (var j = 0; j < errors[name].length; j++) {
        var li = document.createElement('li');
        li.textContent = errors[name][j];
        ul.appendChild(li);
      }
      host.appendChild(ul);
      if (!first) first = host;
    }
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  form.addEventListener('submit', function (e) {
    if (form.getAttribute('data-native-submit') === 'true') return;

    // Guard: bio over the 50-word limit blocks submission.
    if (form.getAttribute('data-bio-over') === 'true') {
      e.preventDefault();
      if (bio) bio.focus();
      return;
    }

    // AJAX path.
    e.preventDefault();
    setBusy(true);

    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (r) {
        if (r.ok && r.data && r.data.success) {
          showConfirmation();
        } else if (r.data && r.data.errors) {
          setBusy(false);
          renderErrors(r.data.errors);
        } else {
          // Not our JSON contract -> normal submit keeps the user safe.
          nativeSubmit();
        }
      })
      .catch(function () {
        nativeSubmit();
      });
  });
})();
