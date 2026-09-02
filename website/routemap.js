/* The rotating example route map. Loaded only on the page that renders it.
   Respects prefers-reduced-motion and WCAG 2.2.2: the rotation pauses on
   hover/focus, skips hidden tabs, and stops after two full cycles. */
(function () {
  // Rotating hero route map — one of four example students, random start.
  // Eight stops = a full four-year degree (Fall/Spring, summers off), stepping
  // up-right in four tiers of two.
  var XS = [70, 165, 270, 365, 470, 565, 670, 765];
  var YS = [172, 172, 132, 132, 92, 92, 52, 52];
  // Full route polyline from start to the destination pin.
  var PTS = [[20, 172], [200, 172], [235, 132], [400, 132], [435, 92], [600, 92], [635, 52], [800, 52], [872, 36]];

  // Every route is a full 120-credit, eight-semester degree with Fall 2026 the
  // term in progress. Completed credits = sum of finished terms; the finished +
  // in-progress + planned terms always total 120.
  var SCENARIOS = [
    {
      // Senior — one semester from the finish line.
      major: "Enterprise Technology Integration, B.S.",
      credits: "90 / 120", eta: "MAY 2027", pinDate: "May 2027", cur: 6,
      stops: [["Fall 2023", "15 cr"], ["Spring 2024", "16 cr"], ["Fall 2024", "15 cr"],
              ["Spring 2025", "15 cr"], ["Fall 2025", "14 cr"], ["Spring 2026", "15 cr"],
              ["Fall 2026", "in progress · 15 cr"], ["Spring 2027", "planned"]]
    },
    {
      // Junior — a December finisher (spring start).
      major: "Accounting, B.S.",
      credits: "75 / 120", eta: "DEC 2027", pinDate: "Dec 2027", cur: 5,
      stops: [["Spring 2024", "15 cr"], ["Fall 2024", "16 cr"], ["Spring 2025", "14 cr"],
              ["Fall 2025", "15 cr"], ["Spring 2026", "15 cr"], ["Fall 2026", "in progress · 15 cr"],
              ["Spring 2027", "planned"], ["Fall 2027", "planned"]]
    },
    {
      // Sophomore — plenty of road ahead.
      major: "Marketing, B.S.",
      credits: "30 / 120", eta: "MAY 2029", pinDate: "May 2029", cur: 2,
      stops: [["Fall 2025", "15 cr"], ["Spring 2026", "15 cr"], ["Fall 2026", "in progress · 16 cr"],
              ["Spring 2027", "planned"], ["Fall 2027", "planned"], ["Spring 2028", "planned"],
              ["Fall 2028", "planned"], ["Spring 2029", "planned"]]
    },
    {
      // Second-year — another December track.
      major: "Psychology, B.S.",
      credits: "45 / 120", eta: "DEC 2028", pinDate: "Dec 2028", cur: 3,
      stops: [["Spring 2025", "15 cr"], ["Fall 2025", "16 cr"], ["Spring 2026", "14 cr"],
              ["Fall 2026", "in progress · 15 cr"], ["Spring 2027", "planned"], ["Fall 2027", "planned"],
              ["Spring 2028", "planned"], ["Fall 2028", "planned"]]
    }
  ];

  var svg = document.getElementById("rm-svg");
  var title = document.getElementById("rm-title");
  var meta = document.getElementById("rm-meta");
  if (!svg || !title || !meta) return;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function pathD(points) {
    return points.map(function (p, i) { return (i ? "L " : "M ") + p[0] + " " + p[1]; }).join(" ");
  }

  // Split the route polyline at the current stop (always on a horizontal segment).
  function splitAt(k) {
    var cx = XS[k], cy = YS[k];
    var trav = [PTS[0]], i = 1;
    for (; i < PTS.length; i++) {
      var prev = PTS[i - 1], pt = PTS[i];
      if (prev[1] === cy && pt[1] === cy && prev[0] <= cx && cx <= pt[0]) {
        trav.push([cx, cy]);
        break;
      }
      trav.push(pt);
    }
    return { trav: trav, ahead: [[cx, cy]].concat(PTS.slice(i)) };
  }

  function stopMarkup(k, s) {
    var x = XS[k], y = YS[k];
    var label = '<text class="rm-label" x="' + x + '" y="' + (y + 30) + '" text-anchor="middle">' + s.stops[k][0] + "</text>" +
                '<text class="rm-sub" x="' + x + '" y="' + (y + 46) + '" text-anchor="middle">' + s.stops[k][1] + "</text>";
    if (k < s.cur) {
      return "<g><circle cx=\"" + x + "\" cy=\"" + y + "\" r=\"9\" fill=\"#16a34a\"/>" +
        '<path d="M ' + (x - 4) + " " + y + ' l 3 3 l 5.5 -6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
        label + "</g>";
    }
    if (k === s.cur) {
      return '<g><circle class="rm-pulse" cx="' + x + '" cy="' + y + '" r="14" fill="none" stroke="#d97706" stroke-width="3"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="9" fill="#fff" stroke="#d97706" stroke-width="3.5"/>' +
        '<text class="rm-flag" x="' + x + '" y="' + (y - 32) + '" text-anchor="middle">YOU ARE HERE</text>' +
        label + "</g>";
    }
    return '<g><circle cx="' + x + '" cy="' + y + '" r="8" fill="#fff" stroke="#9ca3af" stroke-width="3"/>' + label + "</g>";
  }

  function render(s) {
    var split = splitAt(s.cur);
    var parts = [
      '<path class="rm-traveled" d="' + pathD(split.trav) + '" fill="none" stroke="#1a3a6b" stroke-width="5" stroke-linecap="round"/>',
      '<path d="' + pathD(split.ahead) + '" fill="none" stroke="#2a5298" stroke-width="4" stroke-linecap="round" stroke-dasharray="2 11" opacity="0.75"/>'
    ];
    for (var k = 0; k < s.stops.length; k++) parts.push(stopMarkup(k, s));
    parts.push(
      '<g><path d="M 890 8 c -11.5 0 -20 8.5 -20 19 c 0 13 20 32 20 32 s 20 -19 20 -32 c 0 -10.5 -8.5 -19 -20 -19 z" fill="#1a3a6b"/>' +
      '<circle cx="890" cy="27" r="7.5" fill="#fff"/>' +
      '<text class="rm-dest" x="890" y="92" text-anchor="middle">GRADUATION</text>' +
      '<text class="rm-sub" x="890" y="108" text-anchor="middle">' + s.pinDate + "</text></g>"
    );
    svg.innerHTML = parts.join("");
    // On narrow screens the card scrolls horizontally — center the current stop
    // so "YOU ARE HERE" is visible instead of the leftmost (past) semesters.
    var card = svg.closest(".routemap-card");
    if (card && card.scrollWidth > card.clientWidth + 8) {
      var scale = (svg.clientWidth || 980) / 980;
      card.scrollLeft = Math.max(0, XS[s.cur] * scale - card.clientWidth / 2);
    }
    svg.setAttribute("aria-label",
      "Example route for " + s.major + ": " + s.cur + " semesters completed, one in progress, graduating " + s.pinDate);
    title.textContent = "Route: " + s.major;
    meta.textContent = s.credits + " CR · ETA " + s.eta;
    if (!reduced) {
      var trav = svg.querySelector(".rm-traveled");
      var len = Math.ceil(trav.getTotalLength());
      trav.style.strokeDasharray = len;
      trav.style.strokeDashoffset = len;
    }
  }

  var i = Math.floor(Math.random() * SCENARIOS.length);
  render(SCENARIOS[i]);

  if (!reduced) {
    // Rotate through the example students, but respect WCAG 2.2.2: pause while
    // hovered/focused, skip ticks in hidden tabs, and stop after two full cycles.
    var paused = false, shown = 0;
    var card = svg.closest(".routemap-card");
    if (card) {
      card.addEventListener("mouseenter", function () { paused = true; });
      card.addEventListener("mouseleave", function () { paused = false; });
      card.addEventListener("focusin", function () { paused = true; });
      card.addEventListener("focusout", function () { paused = false; });
    }
    var timer = setInterval(function () {
      if (paused || document.visibilityState === "hidden") return;
      if (++shown >= SCENARIOS.length * 2) clearInterval(timer);
      svg.style.opacity = "0";
      title.style.opacity = "0";
      meta.style.opacity = "0";
      setTimeout(function () {
        i = (i + 1) % SCENARIOS.length;
        render(SCENARIOS[i]);
        svg.style.opacity = "1";
        title.style.opacity = "1";
        meta.style.opacity = "1";
      }, 320);
    }, 8000);
  }
})();
