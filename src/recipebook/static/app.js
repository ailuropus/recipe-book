/* Sending a slow form, once.
 *
 * Two kinds. `data-once` forms — import and revise — only start a job and
 * redirect to a page that waits on it, so all they need is to refuse a second
 * press, which would pay for the same call twice. `data-busy` forms — the
 * question on a recipe page — hold the request open for the ten seconds the
 * answer takes, so they also put up the waiting room.
 *
 * Progressive enhancement: with JavaScript off, every form still submits and
 * still works. This only adds the lock and the waiting room.
 */
(function () {
  "use strict";

  var overlay = document.getElementById("busy");

  var forms = document.querySelectorAll("form[data-busy], form[data-once]");
  if (!forms.length) return;

  var clip = overlay && overlay.querySelector("video");

  // The overlay's clip has to be in memory before the form is sent. Once a
  // form post is under way the browser stops loading anything more for the
  // page it is leaving, and a clip that was never fetched in full freezes
  // after a loop or two — a phone that ignores preload freezes almost at
  // once. A blob URL plays from memory, with no network left to lose.
  if (clip && document.querySelector("form[data-busy]") && window.fetch && window.URL) {
    var sources = clip.querySelectorAll("source");
    for (var i = 0; i < sources.length; i++) {
      if (!clip.canPlayType(sources[i].type)) continue;
      fetch(sources[i].src)
        .then(function (response) {
          return response.ok ? response.blob() : null;
        })
        .then(function (blob) {
          if (!blob) return;
          clip.src = URL.createObjectURL(blob);
          if (!overlay.hidden) play();
        })
        .catch(function () {});
      break;
    }
  }

  function play() {
    var playing = clip.play();
    // Autoplay can be refused; the message alone is enough.
    if (playing && typeof playing.catch === "function") playing.catch(function () {});
  }

  function show(message) {
    var label = overlay.querySelector(".busy__label");
    if (label && message) label.textContent = message;
    overlay.hidden = false;
    if (clip) play();
  }

  Array.prototype.forEach.call(forms, function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted) {
        // Second press while the first is still in flight.
        event.preventDefault();
        return;
      }
      form.dataset.submitted = "1";
      if (overlay && form.hasAttribute("data-busy")) show(form.getAttribute("data-busy"));

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
    if (overlay) overlay.hidden = true;
    Array.prototype.forEach.call(forms, function (form) {
      delete form.dataset.submitted;
      Array.prototype.forEach.call(form.querySelectorAll("button, input, textarea, select"), function (el) {
        el.disabled = false;
        el.readOnly = false;
      });
    });
  });
})();

/* The waiting page.
 *
 * The job runs on the server whatever this page does, so all this does is ask
 * every two seconds whether it is finished, and go to the result when it is.
 * `replace` rather than a plain navigation: the back button from the result
 * should reach the form, not a waiting page that bounces straight forward
 * again.
 *
 * A failed request is not a failed job — on a phone it is usually a tunnel or
 * a lock screen — so it is simply asked again. And a tab coming back to the
 * foreground asks at once, rather than waiting out a timer the browser may
 * have been throttling the whole time.
 */
(function () {
  "use strict";

  var wait = document.querySelector("[data-job-status]");
  if (!wait) return;

  var url = wait.getAttribute("data-job-status");
  var timer = null;

  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(check, 2000);
  }

  function check() {
    fetch(url, { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(function (job) {
        if (job.status === "running") schedule();
        else window.location.replace(job.url);
      })
      .catch(schedule);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") check();
  });

  // The clip has autoplay, which a phone in low-power mode refuses; asking
  // explicitly sometimes gets a yes the attribute did not.
  var clip = wait.querySelector("video");
  if (clip) {
    var playing = clip.play();
    if (playing && typeof playing.catch === "function") playing.catch(function () {});
  }

  schedule();
})();

/* The deletion shield.
 *
 * The ten seconds and the disappearing are CSS animations, so the countdown is
 * real with JavaScript off. This only cleans up after them: the element is
 * removed once it has finished, and the `?deleted=` that put it there is taken
 * out of the address bar so a refresh does not start the ten seconds over on a
 * deletion that happened minutes ago.
 */
(function () {
  "use strict";

  var shield = document.getElementById("shield");
  if (!shield) return;

  if (window.history && window.history.replaceState) {
    var url = new URL(window.location.href);
    if (url.searchParams.has("deleted")) {
      url.searchParams.delete("deleted");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }

  shield.addEventListener("animationend", function (event) {
    // The bar finishes at the same moment; only the shield's own animation
    // means the offer has expired.
    if (event.target === shield) shield.remove();
  });
})();
