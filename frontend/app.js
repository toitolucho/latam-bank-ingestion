// Interfaz de chat para el backend (carpeta backend/). Sin dependencias ni paso de compilacion.
// Todo texto que viene de la API se inserta con textContent (nunca innerHTML): no hay inyeccion de HTML.
// Los componentes visuales estan en components.js; aqui vive el estado, la API y el flujo de pantallas.
(function () {
  "use strict";

  var cfg = Object.assign({ apiBase: "", apiKey: "" }, window.CHAT_CONFIG || {});
  var I18N = window.CHAT_I18N;
  var DOC_RE = /^[A-Za-z0-9.\-]{4,32}$/;
  var HEALTH_EVERY_MS = 30000;

  var state = {
    lang: "es",
    view: "login",
    sid: null,
    token: null,
    questions: [],
    attemptsLeft: 0,
    busy: false,
    online: null,            // null = sin comprobar; true/false segun /health y las llamadas a la API
    handoffShown: {},
    customer: null,          // perfil conocido: lo basico al verificar + lo que lea el agente (evidence.customer)
    latest: {},              // ultimos registros devueltos por el backend: evaluation, offer, handoff
    usedSteps: [],           // herramientas usadas en el ultimo turno (marca las fuentes del panel)
    lastEvidence: null,
    lastText: "",
    turnDone: false,         // hubo una respuesta correcta del agente (para mostrar el flujo como completado)
    tracked: [],             // nodos que dependen del idioma y se reconstruyen al cambiarlo: {node, build}
  };

  function $(id) { return document.getElementById(id); }

  // ---------------------------------------------------------------- i18n
  function t(key, vars) {
    var s = key.split(".").reduce(function (o, k) { return o && o[k]; }, I18N[state.lang]);
    if (typeof s !== "string") return key;
    return s.replace(/\{(\w+)\}/g, function (_, k) { return vars && vars[k] !== undefined ? vars[k] : "{" + k + "}"; });
  }
  UNI.t = t;
  UNI.locale = function () { return I18N[state.lang].locale; };

  // id -> clave, para los elementos que ya existian; el resto usa data-i18n / data-i18n-aria en el HTML.
  var TEXT_BY_ID = {
    "login-title": "loginTitle", "login-help": "loginHelp", "doc-label": "docLabel", "login-btn": "start",
    "challenge-title": "challengeTitle", "challenge-back": "back", "verify-btn": "verify", "ended-title": "endedTitle",
    "ended-text": "endedText", "restart-btn": "newChat", "disclaimer": "disclaimer", "pdf-btn": "downloadPdf",
    "input-label": "inputLabel",
  };

  function applyI18n() {
    document.documentElement.lang = I18N[state.lang].htmlLang;
    document.title = t("title");
    Object.keys(TEXT_BY_ID).forEach(function (id) { $(id).textContent = t(TEXT_BY_ID[id]); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n]"), function (n) { n.textContent = t(n.getAttribute("data-i18n")); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-aria]"), function (n) { n.setAttribute("aria-label", t(n.getAttribute("data-i18n-aria"))); });
    $("input").placeholder = t("placeholder");
    Array.prototype.forEach.call(document.querySelectorAll(".lang-opt"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === state.lang));
    });
    updateChallengeHelp();
    renderStatus();
    renderUser();
    rerenderTracked();
    renderPipelines();
    renderPanel();
  }

  function updateChallengeHelp() {
    $("challenge-help").textContent = t("challengeHelp", { n: state.questions.length, left: state.attemptsLeft });
  }

  // ---------------------------------------------------------------- nodos que dependen del idioma
  function track(node, build) {
    state.tracked.push({ node: node, build: build });
    return node;
  }

  function untrack(node) {
    state.tracked = state.tracked.filter(function (x) { return x.node !== node; });
  }

  function rerenderTracked() {
    state.tracked.forEach(function (x) {
      if (!x.node.isConnected) return;
      var det = x.node.querySelector("details.investigation");
      var wasOpen = !!(det && det.open);     // se conserva el acordeon abierto
      var fresh = x.build();
      var newDet = fresh.querySelector("details.investigation");
      if (newDet && wasOpen) newDet.open = true;
      x.node.replaceWith(fresh);
      x.node = fresh;
    });
  }

  // ---------------------------------------------------------------- estado del sistema (/health)
  function setOnline(ok) {
    if (state.online === ok) return;
    state.online = ok;
    renderStatus();
  }

  function renderStatus() {
    var s = state.online === null ? "checking" : (state.online ? "online" : "offline");
    [["sys-status-side", "status." + s], ["sys-status", "status." + s], ["panel-status", state.online ? "status.connected" : "status." + s]]
      .forEach(function (p) {
        var box = $(p[0]);
        box.setAttribute("data-state", s);
        box.querySelector("[data-status-label]").textContent = t(p[1]);
      });
    $("agent-dot").setAttribute("data-state", s);
    $("agent-sub").textContent = t(state.online === false ? "agentSubOffline" : "agentSub");
    renderPanel();
  }

  function checkHealth() {
    if (document.hidden) return;
    fetch(cfg.apiBase + "/health", { cache: "no-store" })
      .then(function (res) { setOnline(res.ok); })
      .catch(function () { setOnline(false); });
  }

  // ---------------------------------------------------------------- vistas y mensajes de error
  function setView(name) {
    state.view = name;
    $("app").setAttribute("data-view", name);
    ["login", "challenge", "chat", "ended"].forEach(function (v) { $("view-" + v).hidden = v !== name; });
    $("end-btn").hidden = name !== "chat";
    $("user-menu").hidden = name !== "chat";
    $("panel-btn").hidden = name !== "chat";
    closeOverlays();
    var focus = { login: "doc", challenge: "verify-btn", chat: "input", ended: "restart-btn" }[name];
    var el = $(focus);
    if (el && !el.disabled) el.focus();
  }

  function showBanner(text) {
    var b = $("banner");
    b.textContent = text;
    b.hidden = !text;
  }

  function errorText(error) {
    var msgs = I18N[state.lang].errors;
    var base = msgs[error.code] || msgs.generic;
    if (!msgs[error.code] && error.trace_id) base += " " + msgs.support + " " + error.trace_id;
    return base;
  }

  function setBusy(busy) {
    state.busy = busy;
    $("composer").classList.toggle("is-busy", busy);
    ["login-btn", "send-btn", "verify-btn"].forEach(function (id) { if (busy) $(id).disabled = true; });
    if (!busy) {
      $("login-btn").disabled = false;
      $("send-btn").disabled = false;
      refreshVerifyEnabled();
    }
  }

  // ---------------------------------------------------------------- API
  function api(method, path, body, auth) {
    var headers = { "Content-Type": "application/json" };
    if (cfg.apiKey) headers["X-API-Key"] = cfg.apiKey;
    if (auth && state.token) headers.Authorization = "Bearer " + state.token;
    return fetch(cfg.apiBase + path, { method: method, headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (res) {
        setOnline(true);
        if (res.status === 204) return { ok: true, status: 204, data: null };
        return res.json().catch(function () { return null; }).then(function (data) {
          if (res.ok) return { ok: true, status: res.status, data: data };
          return { ok: false, status: res.status, error: (data && data.error) || { code: "generic" } };
        });
      })
      .catch(function () { setOnline(false); return { ok: false, status: 0, error: { code: "network" } }; });
  }

  // ---------------------------------------------------------------- 1. documento
  function onLogin(ev) {
    ev.preventDefault();
    if (state.busy) return;
    showBanner("");
    var doc = $("doc").value.trim();
    var err = $("doc-error");
    if (!DOC_RE.test(doc)) {
      err.textContent = t("docInvalid");
      err.hidden = false;
      $("doc").setAttribute("aria-invalid", "true");
      return;
    }
    err.hidden = true;
    $("doc").removeAttribute("aria-invalid");
    setBusy(true);
    api("POST", "/v1/sessions", { document_number: doc, language: state.lang }, false).then(function (r) {
      setBusy(false);
      if (!r.ok) return showBanner(errorText(r.error));
      state.sid = r.data.session_id;
      state.token = r.data.token;
      state.questions = r.data.auth.questions;
      state.attemptsLeft = r.data.auth.attempts_left;
      renderQuestions();
      setView("challenge");
    });
  }

  // ---------------------------------------------------------------- 2. preguntas de seguridad
  function renderQuestions() {
    var box = $("questions");
    box.textContent = "";
    state.questions.forEach(function (q, i) {
      var fs = document.createElement("fieldset");
      fs.className = "question";
      var lg = document.createElement("legend");
      lg.textContent = (i + 1) + ". " + q.text;
      fs.appendChild(lg);
      q.options.forEach(function (o, j) {
        var label = document.createElement("label");
        label.className = "option";
        var input = document.createElement("input");
        input.type = "radio";
        input.name = q.id;
        input.value = o.id;
        input.id = q.id + "-" + j;
        input.addEventListener("change", refreshVerifyEnabled);
        var span = document.createElement("span");
        span.textContent = o.label;
        label.appendChild(input);
        label.appendChild(span);
        fs.appendChild(label);
      });
      box.appendChild(fs);
    });
    updateChallengeHelp();
    refreshVerifyEnabled();
  }

  function selectedAnswers() {
    return state.questions.map(function (q) {
      var checked = document.querySelector('input[name="' + q.id + '"]:checked');
      return checked ? { question_id: q.id, option_id: checked.value } : null;
    });
  }

  function refreshVerifyEnabled() {
    var all = state.questions.length > 0 && selectedAnswers().every(Boolean);
    $("verify-btn").disabled = state.busy || !all;
  }

  function onVerify(ev) {
    ev.preventDefault();
    if (state.busy) return;
    var answers = selectedAnswers();
    if (!answers.every(Boolean)) return;
    showBanner("");
    setBusy(true);
    api("POST", "/v1/sessions/" + encodeURIComponent(state.sid) + "/verify", { answers: answers }, true).then(function (r) {
      setBusy(false);
      if (!r.ok) {
        showBanner(errorText(r.error));
        if (["AUTH_LOCKED", "SESSION_EXPIRED", "INVALID_TOKEN"].indexOf(r.error.code) >= 0) resetSession(true);
        return;
      }
      if (r.data.status === "authenticated") {
        state.customer = r.data.customer || null;
        startChat(r.data.greeting || "", r.data.suggested_replies || []);
        return;
      }
      state.questions = r.data.questions || [];
      state.attemptsLeft = r.data.attempts_left;
      showBanner(r.data.attempts_left === 1 ? t("wrongOne") : t("wrong", { left: r.data.attempts_left }));
      renderQuestions();
    });
  }

  // ---------------------------------------------------------------- 3. chat
  function startChat(greeting, suggestions) {
    $("messages").textContent = "";
    state.tracked = [];
    state.latest = {};
    state.usedSteps = [];
    state.lastEvidence = null;
    setView("chat");
    var buildEmpty = function () { var e = UNI.emptyState(); e.id = "empty-state"; return e; };
    $("messages").appendChild(track(buildEmpty(), buildEmpty));
    renderUser();
    renderPipelines();
    renderPanel();
    addMessage("assistant", greeting);
    showSuggestions(suggestions);
  }

  function userInitial() { return state.customer && state.customer.first_name ? state.customer.first_name : "U"; }

  function renderUser() {
    var c = state.customer;
    $("user-initial").textContent = userInitial().slice(0, 1).toUpperCase();
    $("user-name").textContent = c && c.first_name ? c.first_name : "";
    $("user-meta").textContent = c && c.customer_id ? t("userMeta", { id: c.customer_id }) : "";
    $("user-meta").hidden = !(c && c.customer_id);
  }

  function pushMessage(node) {
    var box = $("messages");
    box.appendChild(node);
    box.scrollTop = box.scrollHeight;
    return node;
  }

  // role: "user" | "assistant". opts: {offer, uncertain, evidence}
  function addMessage(role, text, opts) {
    opts = opts || {};
    var at = new Date();
    if (role === "user") {
      var build = function () { return UNI.userMessage(text, { at: at, initial: userInitial() }); };
      return pushMessage(track(build(), build));
    }
    var buildAgent = function () {
      var m = UNI.agentMessage(text, { offer: opts.offer, uncertain: opts.uncertain, at: at });
      UNI.fillEvidence(m.extras, opts.evidence);
      return m.root;
    };
    return pushMessage(track(buildAgent(), buildAgent));
  }

  function addCallout(build) {
    return pushMessage(track(build(), build));
  }

  function downloadSummary() {
    if (!state.sid) return;
    var headers = {};
    if (cfg.apiKey) headers["X-API-Key"] = cfg.apiKey;
    if (state.token) headers.Authorization = "Bearer " + state.token;
    fetch(cfg.apiBase + "/v1/sessions/" + encodeURIComponent(state.sid) + "/summary.pdf", { headers: headers })
      .then(function (res) {
        if (!res.ok) {
          return res.json().catch(function () { return null; }).then(function (data) {
            throw (data && data.error) || { code: "generic" };
          });
        }
        return res.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "resumen-propuesta.pdf";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      })
      .catch(function (err) { showBanner(errorText(err && err.code ? err : { code: "network" })); });
  }

  function addHandoff(ticket) {
    if (!ticket || state.handoffShown[ticket]) return;
    state.handoffShown[ticket] = true;
    addCallout(function () { return UNI.escalationCard(ticket); });
  }

  function addSummaryCard(email) {
    addCallout(function () { return UNI.summaryCard(email, downloadSummary); });
  }

  function showTyping(on) {
    var existing = $("typing");
    if (existing) { untrack(existing); existing.remove(); }
    if (!on) return;
    pushMessage(track(UNI.loadingState(), UNI.loadingState));
  }

  function scrollToEnd() {
    var box = $("messages");
    box.scrollTop = box.scrollHeight;
    // las sugerencias cambian la altura del chat despues de desplazar: se reaplica tras el siguiente dibujo
    window.requestAnimationFrame(function () { box.scrollTop = box.scrollHeight; });
  }

  function showSuggestions(list) {
    var box = $("suggestions");
    box.textContent = "";
    list.forEach(function (text) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = text;
      b.addEventListener("click", function () { send(text); });
      box.appendChild(b);
    });
    scrollToEnd();
  }

  // ---------------------------------------------------------------- evidencia: panel y flujo
  function applyEvidence(ev) {
    state.lastEvidence = ev || null;
    state.usedSteps = ev ? ev.steps.map(function (s) { return s.id; }) : [];
    if (!ev) return;
    if (ev.customer) state.customer = Object.assign({}, state.customer || {}, ev.customer);
    if (ev.evaluation) state.latest.evaluation = ev.evaluation;
    ev.steps.forEach(function (s) {
      if (s.id === "offer_rates") state.latest.offer = s.data;
      if (s.id === "handoff") state.latest.handoff = { ticket: s.data.ticket };
    });
  }

  function renderPipelines() {
    var showcase = UNI.agentPipeline(UNI.pipelineState("idle"), { showcase: true });
    showcase.classList.add("pipeline-showcase");
    $("pipeline-login").replaceChildren(showcase);
    var phase = state.busy && state.view === "chat" ? "working" : (state.lastEvidence !== null || state.turnDone ? "done" : "idle");
    $("pipeline-chat").replaceChildren(UNI.agentPipeline(UNI.pipelineState(phase, state.lastEvidence)));
  }

  function renderPanel() {
    $("panel-sources").replaceChildren(UNI.dataSources(state.usedSteps, state.online !== false));
    $("panel-relevant").replaceChildren(UNI.sectionTitle("relevant-title", t("panel.relevant")), UNI.relevantData(state.latest));
    $("panel-profile").replaceChildren(UNI.sectionTitle("profile-title", t("panel.profile")), UNI.customerProfile(state.customer));
  }

  // ---------------------------------------------------------------- envio
  function showError(error, text) {
    var canContact = error.code !== "network";
    addCallout(function () {
      var card = UNI.errorState(errorText(error), {
        onRetry: function () { untrack(card); card.remove(); send(text, { retry: true }); },
        onContact: canContact ? function () { untrack(card); card.remove(); send(t("error.contactPhrase")); } : null,
      });
      return card;
    });
  }

  function send(text, opts) {
    opts = opts || {};
    text = (text || "").trim();
    if (!text || state.busy) return;
    showBanner("");
    showSuggestions([]);
    var empty = $("empty-state");
    if (empty) { untrack(empty); empty.remove(); }
    if (!opts.retry) addMessage("user", text);
    state.lastText = text;
    $("input").value = "";
    setBusy(true);
    $("input").disabled = true;
    state.turnDone = false;
    renderPipelines();
    showTyping(true);
    api("POST", "/v1/sessions/" + encodeURIComponent(state.sid) + "/messages", { message: text, language: state.lang }, true)
      .then(function (r) {
        showTyping(false);
        setBusy(false);
        $("input").disabled = false;
        state.turnDone = r.ok;
        if (!r.ok) {
          state.lastEvidence = null;
          state.usedSteps = [];
          renderPipelines();
          renderPanel();
          if (["SESSION_EXPIRED", "INVALID_TOKEN"].indexOf(r.error.code) >= 0) {
            resetSession(false);
            showBanner(errorText(r.error));
            return;
          }
          showError(r.error, text);
          $("input").focus();
          return;
        }
        var d = r.data;
        applyEvidence(d.evidence);
        var uncertain = d.awaiting === "confirm_handoff" || d.outcome === "needs_review" || d.outcome === "needs_data";
        addMessage("assistant", d.reply, { offer: d.proactive_offer, uncertain: uncertain, evidence: d.evidence });
        addHandoff(d.handoff_ticket);
        if (d.summary_ready) { state.hasSummary = true; addSummaryCard(d.email); }
        showSuggestions(d.suggested_replies || []);
        renderUser();
        renderPipelines();
        renderPanel();
        $("input").focus();
      });
  }

  // ---------------------------------------------------------------- cierre y reinicio
  function clearConversation() {
    state.customer = null;
    state.latest = {};
    state.usedSteps = [];
    state.lastEvidence = null;
    state.turnDone = false;
    state.tracked = [];
    renderUser();
    renderPipelines();
    renderPanel();
  }

  function resetSession(backToLogin) {
    state.sid = null;
    state.token = null;
    state.questions = [];
    state.handoffShown = {};
    state.hasSummary = false;
    $("ended-reply").hidden = true; $("ended-email").hidden = true; $("pdf-btn").hidden = true;
    showTyping(false);
    showSuggestions([]);
    $("input").disabled = false;
    clearConversation();
    if (backToLogin) { $("doc").value = ""; setView("login"); } else { setView("ended"); }
  }

  function emailLine(email) {
    return email && email.to ? t("summaryReady", { to: email.to }) : t("summaryReadyNoAddr");
  }

  function onEnd() {
    var sid = state.sid;
    showBanner("");
    if (!sid || state.busy) return resetSession(false);
    setBusy(true);
    api("POST", "/v1/sessions/" + encodeURIComponent(sid) + "/end", null, true).then(function (r) {
      setBusy(false);
      if (!r.ok) { showBanner(errorText(r.error)); return resetSession(false); }
      var d = r.data;
      state.hasSummary = state.hasSummary || d.summary_ready;
      $("ended-reply").textContent = d.reply;
      $("ended-reply").hidden = !d.reply;
      $("ended-email").textContent = d.summary_ready ? emailLine(d.email) : "";
      $("ended-email").hidden = !d.summary_ready;
      $("pdf-btn").hidden = !state.hasSummary;
      showTyping(false);
      showSuggestions([]);
      clearConversation();
      setView("ended");           // se conserva la sesion para poder descargar el PDF hasta "Nueva conversacion"
    });
  }

  function onRestart() {
    if (state.sid) api("DELETE", "/v1/sessions/" + encodeURIComponent(state.sid), null, true);
    state.sid = null; state.token = null; state.hasSummary = false; state.handoffShown = {};
    $("ended-reply").hidden = true; $("ended-email").hidden = true; $("pdf-btn").hidden = true;
    showBanner("");
    $("messages").textContent = "";
    $("doc").value = "";
    clearConversation();
    setView("login");
  }

  // ---------------------------------------------------------------- menu de usuario, cajones y teclado
  function setExpanded(btn, open) { btn.setAttribute("aria-expanded", String(open)); }

  function toggleUserMenu(open) {
    $("user-popover").hidden = !open;
    setExpanded($("user-btn"), open);
  }

  // Cajones en pantallas angostas: el menu lateral (izquierda) y el panel de investigacion (derecha / hoja inferior).
  function setDrawer(which, open) {
    var app = $("app");
    app.setAttribute("data-" + which, open ? "open" : "closed");
    setExpanded($(which === "nav" ? "nav-btn" : "panel-btn"), open);
    $("scrim").hidden = !(app.getAttribute("data-nav") === "open" || app.getAttribute("data-panel") === "open");
  }

  function closeOverlays() {
    toggleUserMenu(false);
    setDrawer("nav", false);
    setDrawer("panel", false);
  }

  function initOverlays() {
    $("user-btn").addEventListener("click", function (ev) { ev.stopPropagation(); toggleUserMenu($("user-popover").hidden); });
    $("nav-btn").addEventListener("click", function () { setDrawer("nav", $("app").getAttribute("data-nav") !== "open"); $("nav-close").focus(); });
    $("nav-close").addEventListener("click", function () { setDrawer("nav", false); $("nav-btn").focus(); });
    $("panel-btn").addEventListener("click", function () {
      var open = $("app").getAttribute("data-panel") !== "open";
      setDrawer("panel", open);
      if (open) $("panel-close").focus();
    });
    $("panel-close").addEventListener("click", function () { setDrawer("panel", false); $("panel-btn").focus(); });
    $("scrim").addEventListener("click", closeOverlays);
    document.addEventListener("click", function (ev) {
      if (!$("user-menu").contains(ev.target)) toggleUserMenu(false);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeOverlays();
      // "/" lleva el foco al cuadro de mensaje, salvo que ya se este escribiendo en un campo
      var tag = (ev.target && ev.target.tagName) || "";
      if (ev.key === "/" && state.view === "chat" && !/INPUT|TEXTAREA|SELECT/.test(tag) && !$("input").disabled) {
        ev.preventDefault();
        $("input").focus();
      }
    });
  }

  // ---------------------------------------------------------------- arranque
  function init() {
    var saved = (navigator.language || "es").slice(0, 2);
    state.lang = saved === "pt" ? "pt" : "es";
    Array.prototype.forEach.call(document.querySelectorAll(".lang-opt"), function (b) {
      b.addEventListener("click", function () {
        state.lang = b.getAttribute("data-lang");
        applyI18n();
      });
    });
    $("login-form").addEventListener("submit", onLogin);
    $("challenge-form").addEventListener("submit", onVerify);
    $("challenge-back").addEventListener("click", function () { showBanner(""); resetSession(true); });
    $("composer").addEventListener("submit", function (ev) { ev.preventDefault(); send($("input").value); });
    $("end-btn").addEventListener("click", function () { toggleUserMenu(false); onEnd(); });
    $("restart-btn").addEventListener("click", onRestart);
    $("pdf-btn").addEventListener("click", downloadSummary);
    $("agent-avatar-slot").appendChild(UNI.avatar("agent", { large: true }));
    initOverlays();
    applyI18n();
    setView("login");
    checkHealth();
    setInterval(checkHealth, HEALTH_EVERY_MS);
    document.addEventListener("visibilitychange", checkHealth);
  }

  init();
})();
