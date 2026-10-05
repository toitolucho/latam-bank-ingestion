// Componentes de la interfaz (JS plano, sin compilación): funciones que construyen DOM a partir de datos.
// Reglas: todo texto entra con textContent (nunca innerHTML) y nada se muestra si el backend no lo envió:
// la investigación, los sellos de verificación y los registros salen de `evidence` (ver backend/app/agent/evidence.py).
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var UNI = (window.UNI = {
    // las asigna app.js: traducción y configuración regional del idioma activo
    t: function (key) { return key; },
    locale: function () { return "es-MX"; },
  });

  // ---------------------------------------------------------------- utilidades
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function icon(name, cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function append(parent, children) {
    children.forEach(function (c) { if (c) parent.appendChild(c); });
    return parent;
  }

  var t = function (key, vars) { return UNI.t(key, vars); };

  // ---------------------------------------------------------------- formatos (por idioma, sin texto fijo)
  var fmt = {
    number: function (n, digits) {
      return new Intl.NumberFormat(UNI.locale(), { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 }).format(n);
    },
    // "82.071 MXN": mismo estilo que los textos del agente (monto y luego codigo de moneda)
    money: function (amount, ccy, digits) {
      if (amount === null || amount === undefined) return t("field.none");
      return fmt.number(amount, digits) + " " + ccy;
    },
    pct: function (n, digits) {
      return new Intl.NumberFormat(UNI.locale(), { minimumFractionDigits: digits === undefined ? 1 : digits,
        maximumFractionDigits: digits === undefined ? 1 : digits }).format(n) + "%";
    },
    date: function (iso) {            // "2026-06-17" -> fecha local; no se interpreta como UTC para no correr un día
      var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
      if (!m) return iso || t("field.none");
      return new Intl.DateTimeFormat(UNI.locale(), { day: "2-digit", month: "2-digit", year: "numeric" })
        .format(new Date(+m[1], +m[2] - 1, +m[3]));
    },
    time: function (d) {
      return new Intl.DateTimeFormat(UNI.locale(), { hour: "2-digit", minute: "2-digit" }).format(d || new Date());
    },
  };
  UNI.fmt = fmt;

  function account(status) {
    return status === "Active" ? t("field.accountActive") : t("field.accountOther", { status: status });
  }

  // ---------------------------------------------------------------- common
  UNI.icon = icon;

  UNI.avatar = function (kind, opts) {
    opts = opts || {};
    var a = el("span", "avatar avatar-" + kind + (opts.large ? " avatar-lg" : "") + (opts.active ? " is-active" : ""));
    if (kind === "agent") {
      var img = el("img");
      img.src = "assets/unicorn.svg";
      img.alt = "";
      img.width = img.height = opts.large ? 48 : 32;
      a.appendChild(img);
    } else {
      a.textContent = (opts.initial || "?").slice(0, 1).toUpperCase();
    }
    a.setAttribute("aria-hidden", "true");
    return a;
  };

  // Sello de estado: tone = ok | warn | info | error
  UNI.statusBadge = function (tone, text, iconName) {
    return append(el("span", "sbadge sbadge-" + tone), [iconName ? icon(iconName, "icon-sm") : null, el("span", null, text)]);
  };

  // ---------------------------------------------------------------- chat: verificación y herramientas
  var VERIFY_TONE = { verified: "ok", reference: "info", inconclusive: "warn", unverified: "warn" };
  var VERIFY_ICON = { verified: "check", reference: "database", inconclusive: "alert", unverified: "alert" };

  // v = {code, status} tal como lo envía el backend: el texto depende del par código/estado.
  UNI.verificationBadge = function (v) {
    var key = v.status === "inconclusive" ? v.code + "_inconclusive" : v.code;
    var text = t("verify_badge." + key);
    return UNI.statusBadge(VERIFY_TONE[v.status] || "info", text, VERIFY_ICON[v.status] || "check");
  };

  function kv(rows) {
    var dl = el("dl", "kv");
    rows.forEach(function (r) {
      if (!r || r[1] === null || r[1] === undefined || r[1] === "") return;
      var row = el("div", "kv-row");
      row.appendChild(el("dt", null, r[0]));
      row.appendChild(el("dd", null, r[1]));
      dl.appendChild(row);
    });
    return dl;
  }
  UNI.kv = kv;

  function reasonsText(reasons) {
    return (reasons || []).map(function (r) {
      var s = t("reason." + r);
      return s === "reason." + r ? r : s;
    }).join(" · ");
  }

  // Describe un paso a partir de sus datos reales. Devuelve {title, rows}.
  function describeStep(step) {
    var d = step.data || {};
    switch (step.id) {
      case "customer_profile":
        return { title: t("evidence.step.customer_profile"), rows: [[t("field.status"), account(d.status)]] };
      case "fx_rates":
        if (step.status === "failed") return { title: t("evidence.step.fx_rates_failed"), rows: [[d.src + " → " + d.dst, t("evidence.failed")]] };
        return { title: t("evidence.step.fx_rates"), rows: [
          [t("field.fxRate"), t("field.rate1", { src: d.src, dst: d.dst, rate: fmt.number(d.rate, 2) })],
          [t("field.asOf"), fmt.date(d.as_of)]] };
      case "credit_policy":
        return { title: t("evidence.step.credit_policy"), rows: [
          [t("field.outcome"), t("outcome." + d.outcome)],
          [t("field.dti"), d.dti_after === null || d.dti_after === undefined ? null
            : t("field.dtiLimit", { value: fmt.pct(d.dti_after * 100), limit: fmt.pct(d.max_dti * 100, 0) })],
          [t("field.reasons"), reasonsText(d.reasons)],
          [t("field.policyVersion"), d.policy_version]] };
      case "offer_rates":
        return { title: t("evidence.step.offer_rates"), rows: Object.keys(d.rates || {}).map(function (p) {
          return [t("product." + p), fmt.pct(d.rates[p])];
        }).concat([[t("field.maxAmount"), d.max_amount > 0 ? fmt.money(d.max_amount, d.ccy) : null]]) };
      case "handoff":
        return { title: t("evidence.step.handoff"), rows: [[t("field.case"), d.ticket]] };
      case "summary_email":
        return { title: t("evidence.step.summary_email"), rows: [[t("field.email"), d.to], [null, t("evidence.emailSimulated")]] };
      default:
        return { title: step.id, rows: [] };
    }
  }

  // Fila de actividad de una herramienta: "✓ Validé la política de crédito" + sus datos.
  UNI.toolActivity = function (step) {
    var info = describeStep(step);
    var li = el("li", "tool tool-" + step.status);
    li.appendChild(el("span", "tool-mark", null)).appendChild(icon(step.status === "failed" ? "x" : "check"));
    var body = el("div", "tool-body");
    body.appendChild(el("p", "tool-title", info.title));
    var dl = el("dl", "kv");
    info.rows.forEach(function (r) {
      if (r[1] === null || r[1] === undefined || r[1] === "") return;
      var row = el("div", "kv-row" + (r[0] ? "" : " kv-note"));
      if (r[0]) row.appendChild(el("dt", null, r[0]));
      row.appendChild(el("dd", null, r[1]));
      dl.appendChild(row);
    });
    if (dl.childNodes.length) body.appendChild(dl);
    li.appendChild(body);
    return li;
  };

  // Detalles de la investigación (acordeón, cerrado por defecto: el detalle técnico no se impone al cliente).
  UNI.investigationDetails = function (evidence) {
    var det = el("details", "investigation");
    var sum = el("summary", "investigation-summary");
    var n = evidence.steps.length;
    append(sum, [icon("database", "icon-sm"), el("span", "investigation-title", t("evidence.summary")),
      el("span", "investigation-count", n === 1 ? t("evidence.stepsOne") : t("evidence.steps", { n: n })), icon("chevron", "icon-sm chev")]);
    det.appendChild(sum);
    var list = el("ol", "tools");
    evidence.steps.forEach(function (s) { list.appendChild(UNI.toolActivity(s)); });
    det.appendChild(list);
    return det;
  };

  // Rellena (o vuelve a rellenar, p. ej. al cambiar de idioma) los sellos y la investigación de un mensaje del agente.
  UNI.fillEvidence = function (container, evidence) {
    container.textContent = "";
    if (!evidence) return;
    var failed = evidence.steps.some(function (s) { return s.status === "failed"; });
    if (failed) {
      container.appendChild(append(el("div", "vbadges"), [UNI.statusBadge("error", t("evidence.notVerified"), "alert")]));
    } else if (evidence.verification.length) {
      var badges = el("div", "vbadges");
      evidence.verification.forEach(function (v) { badges.appendChild(UNI.verificationBadge(v)); });
      container.appendChild(badges);
    }
    container.appendChild(UNI.investigationDetails(evidence));
  };

  // ---------------------------------------------------------------- chat: mensajes
  UNI.userMessage = function (text, opts) {
    var row = el("article", "msg msg-user");
    row.appendChild(el("span", "visually-hidden", t("you") + ": "));
    var card = el("div", "msg-card");
    card.appendChild(el("p", "msg-text", text));
    card.appendChild(el("time", "msg-time", fmt.time(opts && opts.at)));
    row.appendChild(card);
    row.appendChild(UNI.avatar("user", { initial: opts && opts.initial }));
    return row;
  };

  // opts: {offer, uncertain, error, at}. Devuelve {root, extras}: `extras` recibe sellos e investigación.
  UNI.agentMessage = function (text, opts) {
    opts = opts || {};
    var row = el("article", "msg msg-agent" + (opts.offer ? " is-offer" : "") + (opts.uncertain ? " is-uncertain" : "") + (opts.error ? " is-error" : ""));
    row.appendChild(el("span", "visually-hidden", t("assistant") + ": "));
    row.appendChild(UNI.avatar("agent"));
    var card = el("div", "msg-card");
    var head = el("div", "msg-head");
    head.appendChild(el("span", "msg-author", "UNICORN"));
    head.appendChild(el("time", "msg-time", fmt.time(opts.at)));
    card.appendChild(head);
    var tags = el("div", "msg-tags");
    if (opts.offer) tags.appendChild(UNI.statusBadge("ok", t("offer"), "spark"));
    if (opts.uncertain) tags.appendChild(UNI.statusBadge("warn", t("uncertain"), "headset"));
    if (tags.childNodes.length) card.appendChild(tags);
    card.appendChild(el("p", "msg-text", text));
    var extras = el("div", "msg-extras");
    card.appendChild(extras);
    row.appendChild(card);
    return { root: row, extras: extras };
  };

  UNI.escalationCard = function (ticket) {
    var card = el("div", "callout callout-escalation");
    card.setAttribute("role", "status");
    card.appendChild(el("span", "callout-icon")).appendChild(icon("headset"));
    var body = el("div", "callout-body");
    body.appendChild(el("p", "callout-title", t("escalation.title")));
    body.appendChild(el("p", "callout-text", t("escalation.text")));
    body.appendChild(append(el("p", "case-no"), [el("span", null, t("escalation.case") + " "), el("strong", "mono", "#" + ticket)]));
    card.appendChild(body);
    return card;
  };

  UNI.summaryCard = function (email, onDownload) {
    var card = el("div", "callout callout-summary");
    card.setAttribute("role", "status");
    card.appendChild(el("span", "callout-icon")).appendChild(icon("file"));
    var body = el("div", "callout-body");
    body.appendChild(el("p", "callout-title", t("summaryTitle")));
    body.appendChild(el("p", "callout-text", email && email.to ? t("summaryReady", { to: email.to }) : t("summaryReadyNoAddr")));
    var b = el("button", "btn btn-quiet btn-compact");
    b.type = "button";
    append(b, [icon("download", "icon-sm"), el("span", null, t("downloadPdf"))]);
    b.addEventListener("click", onDownload);
    body.appendChild(b);
    card.appendChild(body);
    return card;
  };

  // Error legible: nunca se presenta como autoritativa una respuesta tras un fallo.
  UNI.errorState = function (message, opts) {
    var card = el("div", "callout callout-error");
    card.setAttribute("role", "alert");
    card.appendChild(el("span", "callout-icon")).appendChild(icon("alert"));
    var body = el("div", "callout-body");
    body.appendChild(el("p", "callout-title", message));
    body.appendChild(el("p", "callout-text", t("error.notVerified")));
    var actions = el("div", "callout-actions");
    var retry = el("button", "btn btn-primary btn-compact");
    retry.type = "button";
    append(retry, [icon("refresh", "icon-sm"), el("span", null, t("error.retry"))]);
    retry.addEventListener("click", opts.onRetry);
    actions.appendChild(retry);
    if (opts.onContact) {
      var contact = el("button", "btn btn-quiet btn-compact", t("error.contact"));
      contact.type = "button";
      contact.addEventListener("click", opts.onContact);
      actions.appendChild(contact);
    }
    body.appendChild(actions);
    card.appendChild(body);
    return card;
  };

  // En lugar de un spinner: el unicornio trabajando. No hay pasos inventados: solo se sabe que está en curso.
  UNI.loadingState = function () {
    var row = el("div", "msg msg-agent msg-loading");
    row.id = "typing";
    row.setAttribute("role", "status");
    row.appendChild(UNI.avatar("agent", { active: true }));
    var card = el("div", "msg-card");
    card.appendChild(el("p", "msg-text loading-text", t("investigating")));
    card.appendChild(el("span", "progress")).appendChild(el("span", "progress-bar"));
    row.appendChild(card);
    return row;
  };

  // Estado vacío del chat: mascota con detalles de píxeles.
  UNI.emptyState = function () {
    var box = el("div", "empty");
    var mark = el("div", "hero hero-sm");
    var img = el("img", "hero-mark");
    img.src = "assets/unicorn.svg";
    img.alt = "";
    img.width = img.height = 96;
    mark.appendChild(img);
    ["a", "b", "c", "d"].forEach(function (k) { mark.appendChild(el("span", "pixel pixel-" + k)); });
    box.appendChild(mark);
    box.appendChild(el("p", "empty-title", t("hero.title")));
    box.appendChild(el("p", "empty-text", t("hero.text")));
    return box;
  };

  // ---------------------------------------------------------------- agente: flujo Cliente → Agente → Datos → Validación → Respuesta
  var STAGES = [
    { id: "customer", icon: "chat" }, { id: "agent", icon: "cpu" }, { id: "data", icon: "database" },
    { id: "validation", icon: "shield" }, { id: "answer", icon: "check-circle" },
  ];
  var DATA_STEPS = ["customer_profile", "fx_rates", "offer_rates"];

  // Estado del flujo según lo que realmente ocurrió. phase: idle | working | done
  UNI.pipelineState = function (phase, evidence) {
    if (phase === "idle") return { customer: "idle", agent: "idle", data: "idle", validation: "idle", answer: "idle" };
    if (phase === "working") return { customer: "done", agent: "active", data: "idle", validation: "idle", answer: "idle" };
    var s = { customer: "done", agent: "done", data: "skipped", validation: "skipped", answer: "done" };
    if (!evidence) return s;
    if (evidence.steps.some(function (x) { return DATA_STEPS.indexOf(x.id) >= 0; })) s.data = "done";
    if (evidence.verification.length || evidence.steps.some(function (x) { return x.type === "validation"; })) s.validation = "done";
    if (evidence.steps.some(function (x) { return x.status === "failed"; })) s.answer = "failed";
    else if (evidence.verification.some(function (v) { return v.status === "verified"; })) {
      // "verificada" solo si TODAS las comprobaciones fueron concluyentes: un dato declarado o una revision pendiente la dejan parcial
      var clean = evidence.verification.every(function (v) { return v.status === "verified" || v.status === "reference"; });
      s.answer = clean ? "verified" : "partial";
    }
    return s;
  };

  // opts.showcase: version explicativa (pantalla de acceso): describe el recorrido completo, sin estados de un turno.
  UNI.agentPipeline = function (state, opts) {
    var showcase = !!(opts && opts.showcase);
    var ol = el("ol", "pipeline");
    ol.setAttribute("aria-label", t("pipeline.label"));
    STAGES.forEach(function (st) {
      var status = state[st.id];
      var label = t("pipeline." + st.id), sub = t("pipeline." + st.id + "Sub");
      if (st.id === "answer" && showcase) { label = t("pipeline.answerVerified"); sub = t("pipeline.answerVerifiedSub"); }
      if (st.id === "answer" && status === "verified") { label = t("pipeline.answerVerified"); sub = t("pipeline.answerVerifiedSub"); }
      if (st.id === "answer" && status === "partial") { label = t("pipeline.answerPartial"); sub = t("pipeline.answerPartialSub"); }
      if (st.id === "answer" && status === "failed") { label = t("pipeline.answerUnverified"); sub = t("pipeline.answerUnverifiedSub"); }
      if (status === "skipped") sub = t("pipeline.skipped");
      if (status === "active") sub = t("pipeline.working");
      var li = el("li", "stage stage-" + status + " stage-id-" + st.id);
      li.appendChild(el("span", "stage-icon")).appendChild(icon(status === "failed" ? "alert" : st.icon));
      var text = el("span", "stage-text");
      text.appendChild(el("span", "stage-label", label));
      text.appendChild(el("span", "stage-sub", sub));
      li.appendChild(text);
      ol.appendChild(li);
    });
    return ol;
  };

  // ---------------------------------------------------------------- panel: datos y herramientas
  var SOURCES = [
    { id: "customer_database", icon: "database", steps: ["customer_profile"] },
    { id: "rules_engine", icon: "shield", steps: ["credit_policy", "offer_rates"] },
    { id: "fx_rates", icon: "swap", steps: ["fx_rates"] },
    { id: "human_support", icon: "headset", steps: ["handoff"] },
  ];

  // usedSteps: ids de los pasos del último turno. online: estado de /health (el mismo para todas las fuentes).
  UNI.dataSources = function (usedSteps, online) {
    var ul = el("ul", "sources");
    SOURCES.forEach(function (src) {
      var used = src.steps.some(function (s) { return usedSteps.indexOf(s) >= 0; });
      var li = el("li", "source" + (used ? " is-used" : ""));
      li.appendChild(el("span", "source-icon")).appendChild(icon(src.icon));
      var body = el("div", "source-body");
      body.appendChild(el("p", "source-name", t("panel.sources." + src.id + ".name")));
      body.appendChild(el("p", "source-desc", t("panel.sources." + src.id + ".desc")));
      li.appendChild(body);
      var mark = el("span", "source-state" + (online ? "" : " is-off"));
      if (used) { mark.title = t("panel.used"); mark.setAttribute("aria-label", t("panel.used")); }
      mark.appendChild(used ? icon("check") : el("span", "dot-status"));
      if (!used) mark.setAttribute("aria-hidden", "true");
      li.appendChild(mark);
      ul.appendChild(li);
    });
    return ul;
  };

  function recordCard(titleText, pill, primaryRows, detailRows) {
    var card = el("article", "record");
    var head = el("div", "record-head");
    head.appendChild(el("h4", "record-title", titleText));
    if (pill) head.appendChild(pill);
    card.appendChild(head);
    card.appendChild(kv(primaryRows));
    var rows = detailRows.filter(function (r) { return r && r[1] !== null && r[1] !== undefined && r[1] !== ""; });
    if (rows.length) {
      var more = kv(rows);
      more.hidden = true;
      more.classList.add("record-more");
      var btn = el("button", "link-btn");
      btn.type = "button";
      btn.setAttribute("aria-expanded", "false");
      var label = el("span", null, t("panel.viewDetails"));
      btn.appendChild(label);
      btn.appendChild(icon("arrow", "icon-sm"));
      btn.addEventListener("click", function () {
        var open = more.hidden;
        more.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
        label.textContent = open ? t("panel.hideDetails") : t("panel.viewDetails");
        card.classList.toggle("is-open", open);
      });
      card.appendChild(more);
      card.appendChild(btn);
    }
    return card;
  }

  var OUTCOME_TONE = { eligible: "ok", eligible_provisional: "warn", declined: "error", needs_review: "warn", needs_data: "warn" };

  // latest = {evaluation, offer, handoff}: lo último que el backend devolvió en cada categoría.
  UNI.relevantData = function (latest) {
    var wrap = el("div", "records");
    var any = false;
    var ev = latest.evaluation;
    if (ev) {
      any = true;
      wrap.appendChild(recordCard(t("panel.evalTitle"), UNI.statusBadge(OUTCOME_TONE[ev.outcome] || "info", t("outcome." + ev.outcome)), [
        [t("product." + ev.product), fmt.money(ev.amount, ev.ccy) + " · " + t("field.months", { n: ev.months })],
        [t("field.dti"), ev.dti_after === null || ev.dti_after === undefined ? null
          : t("field.dtiLimit", { value: fmt.pct(ev.dti_after * 100), limit: fmt.pct(ev.max_dti * 100, 0) })],
      ], [
        [t("field.rate"), ev.rate_pct === null ? null : fmt.pct(ev.rate_pct)],
        [t("field.payment"), ev.payment === null ? null : fmt.money(ev.payment, ev.ccy, 2)],
        [t("field.maxAmount"), ev.max_amount > 0 ? fmt.money(ev.max_amount, ev.ccy) : null],
        [t("field.incomeDeclared"), ev.income_declared ? t("field.incomeDeclaredValue") : t("field.incomeOnFile")],
        [t("field.reasons"), reasonsText(ev.reasons)],
        [t("field.policyVersion"), ev.policy_version],
      ]));
    }
    var offer = latest.offer;
    if (offer && Object.keys(offer.rates).length) {
      any = true;
      wrap.appendChild(recordCard(t("panel.ratesTitle"), null,
        Object.keys(offer.rates).map(function (p) { return [t("product." + p), fmt.pct(offer.rates[p])]; }),
        [[t("field.maxAmount"), offer.max_amount > 0 ? fmt.money(offer.max_amount, offer.ccy) : null]]));
    }
    if (latest.handoff) {
      any = true;
      wrap.appendChild(recordCard(t("panel.caseTitle"), UNI.statusBadge("info", t("panel.sources.human_support.name"), "headset"),
        [[t("field.case"), "#" + latest.handoff.ticket]], []));
    }
    if (!any) return UNI.panelEmpty("database", t("panel.relevantEmpty"));
    return wrap;
  };

  UNI.panelEmpty = function (iconName, text) {
    var box = el("div", "panel-empty");
    box.appendChild(icon(iconName));
    box.appendChild(el("p", null, text));
    return box;
  };

  // Solo muestra los campos que el backend envió: `customer` (al verificar) se completa con lo que lee el agente.
  UNI.customerProfile = function (c) {
    if (!c) return UNI.panelEmpty("user", t("panel.profileEmpty"));
    var rows = [
      [t("field.customerId"), c.customer_id || null],
      [t("field.name"), c.first_name],
      [t("field.status"), c.status ? account(c.status) : null],
      [t("field.segment"), c.segment],
      [t("field.country"), c.country],
      [t("field.income"), c.monthly_income === undefined ? null : (c.monthly_income === null ? t("field.none") : fmt.money(c.monthly_income, c.income_ccy))],
      [t("field.debt"), c.monthly_debt === undefined ? null : fmt.money(c.monthly_debt, c.income_ccy)],
      [t("field.products"), c.active_products === undefined ? null : String(c.active_products)],
      [t("field.pastDue"), c.days_past_due === undefined ? null : String(c.days_past_due)],
    ];
    return append(el("div", "profile-card"), [kv(rows)]);
  };

  UNI.sectionTitle = function (id, text, extra) {
    var head = el("div", "section-title");
    var h = el("h3", null, text);
    h.id = id;
    head.appendChild(h);
    if (extra) head.appendChild(extra);
    return head;
  };
})();
