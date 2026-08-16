/* Busy state for the slow forms.
 *
 * Import takes ~50 seconds, a revision ~75. Without feedback the page looks
 * dead and the natural response is to press the button again, which spends
 * money twice.
 *
 * Progressive enhancement: with JavaScript off, every form still submits and
 * still works. This only adds the waiting room.
 */
(function () {
  "use strict";

  var overlay = document.getElementById("busy");
  if (!overlay) return;

  var forms = document.querySelectorAll("form[data-busy]");
  if (!forms.length) return;

  function show(message) {
    var label = overlay.querySelector(".busy__label");
    if (label && message) label.textContent = message;
    overlay.hidden = false;

    var clip = overlay.querySelector("video");
    if (clip) {
      var playing = clip.play();
      // Autoplay can be refused; the message alone is enough.
      if (playing && typeof playing.catch === "function") playing.catch(function () {});
    }
  }

  Array.prototype.forEach.call(forms, function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted) {
        // Second press while the first is still in flight.
        event.preventDefault();
        return;
      }
      form.dataset.submitted = "1";
      show(form.getAttribute("data-busy"));

      // Deferred by a tick on purpose. The browser serialises the form after
      // this handler returns, and a disabled control is not serialised — the
      // review gate posts which button was pressed as `action`, so disabling
      // it now would submit a decision with no decision in it.
      window.setTimeout(function () {
        Array.prototype.forEach.call(
          form.querySelectorAll("button, input[type=submit]"),
          function (el) {
            el.disabled = true;
          }
        );
        Array.prototype.forEach.call(
          form.querySelectorAll("input, textarea, select"),
          function (el) {
            if (el.type !== "hidden") el.readOnly = true;
          }
        );
      }, 0);
    });
  });

  // Coming back via the back button restores the page from the bfcache with
  // the overlay still up and the form still locked. Undo all of it.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    overlay.hidden = true;
    Array.prototype.forEach.call(forms, function (form) {
      delete form.dataset.submitted;
      Array.prototype.forEach.call(form.querySelectorAll("button, input, textarea, select"), function (el) {
        el.disabled = false;
        el.readOnly = false;
      });
    });
  });
})();
