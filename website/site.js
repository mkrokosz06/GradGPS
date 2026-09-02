/* Shared behaviour for every page: the mobile nav disclosure and the support
   form. Both are no-ops on pages that don't contain them. */
(function () {
  "use strict";

  /* ---------- mobile navigation (W3C disclosure pattern) ----------
     Not role="menu" — that role promises menu-widget keyboard semantics
     assistive tech expects and we don't implement. A button that discloses a
     list of links is the correct pattern for site navigation. */
  (function nav() {
    var toggle = document.getElementById("nav-toggle");
    var menu = document.getElementById("nav-menu");
    if (!toggle || !menu) return;
    var wrapper = toggle.closest(".site-nav");

    function setOpen(open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      wrapper.classList.toggle("nav-open", open);
    }

    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    // Escape closes and returns focus to the button that opened it.
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (toggle.getAttribute("aria-expanded") !== "true") return;
      setOpen(false);
      toggle.focus();
    });

    // Moving focus or clicking outside the nav closes it.
    document.addEventListener("focusin", function (e) {
      if (!wrapper.contains(e.target)) setOpen(false);
    });
    document.addEventListener("click", function (e) {
      if (!wrapper.contains(e.target)) setOpen(false);
    });

    // The panel is only a panel on narrow screens; drop the state on resize
    // so it can't strand an aria-expanded="true" on a desktop layout.
    window.addEventListener("resize", function () {
      if (window.innerWidth > 860) setOpen(false);
    });
  })();

  /* ---------- support form ---------- */
  (function supportForm() {
    var API = "https://kjn2ysmnjr.us-east-1.awsapprunner.com";
    var form = document.getElementById("support-form");
    if (!form) return;

    var status = document.getElementById("sf-status");
    var submit = document.getElementById("sf-submit");
    var email = document.getElementById("sf-email");
    var message = document.getElementById("sf-message");

    function setStatus(text, kind) {
      status.textContent = text;
      status.className = "form-status" + (kind ? " " + kind : "");
    }

    // WCAG 3.3.1/3.3.3: the error goes next to the field, is referenced by
    // aria-describedby, and the field is flagged aria-invalid.
    function setFieldError(input, text) {
      var box = document.getElementById(input.id + "-error");
      if (box) box.textContent = text || "";
      if (text) {
        input.setAttribute("aria-invalid", "true");
        input.focus();
      } else {
        input.removeAttribute("aria-invalid");
      }
    }

    function clearErrors() {
      setFieldError(email, "");
      setFieldError(message, "");
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      clearErrors();

      var emailValue = email.value.trim();
      var messageValue = message.value.trim();

      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(emailValue)) {
        setFieldError(email, "Enter a valid email address so we can reply.");
        setStatus("Check the highlighted field.", "err");
        return;
      }
      if (messageValue.length < 10) {
        setFieldError(message, "Add a bit more detail — what happened, and what did you expect?");
        setStatus("Check the highlighted field.", "err");
        return;
      }

      submit.disabled = true;
      setStatus("Sending…", "");

      fetch(API + "/support/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailValue,
          subject: document.getElementById("sf-subject").value.trim() || null,
          message: messageValue,
          website: document.getElementById("sf-website").value || null
        })
      }).then(function (res) {
        if (res.ok) {
          form.reset();
          setStatus("Message sent — we'll reply to " + emailValue + ".", "ok");
          return;
        }
        return res.json().catch(function () { return null; }).then(function (data) {
          // The 409 detail is an object, so only trust a string.
          var detail = data && typeof data.detail === "string"
            ? data.detail
            : "Something went wrong on our end (error " + res.status + ") — please try again in a minute.";
          setStatus(detail, "err");
        });
      }).catch(function () {
        setStatus("Couldn't reach the server — check your connection and try again.", "err");
      }).finally(function () {
        submit.disabled = false;
      });
    });
  })();
})();
