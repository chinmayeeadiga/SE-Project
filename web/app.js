/* Frontend — vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error body */ }
    if (!res.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
    }
    return data;
  }

  /* ---------- tiny, safe markdown renderer (escapes first) ---------- */
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  }
  function md(src) {
    const lines = String(src || "").split(/\r?\n/);
    let out = "", list = false, i = 0;
    const closeList = () => { if (list) { out += "</ul>"; list = false; } };
    while (i < lines.length) {
      const ln = lines[i];
      if (/^\s*\|.*\|\s*$/.test(ln) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
        closeList();
        const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const head = cells(ln);
        i += 2;
        let rows = "";
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          rows += "<tr>" + cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
          i++;
        }
        out += `<table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
        continue;
      }
      let m;
      if ((m = ln.match(/^(#{1,4})\s+(.*)$/))) { closeList(); out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; }
      else if (/^\s*---+\s*$/.test(ln)) { closeList(); out += "<hr>"; }
      else if ((m = ln.match(/^\s*[-*]\s+(.*)$/))) { if (!list) { out += "<ul>"; list = true; } out += `<li>${inline(m[1])}</li>`; }
      else if (ln.trim() === "") { closeList(); }
      else { closeList(); out += `<p>${inline(ln)}</p>`; }
      i++;
    }
    closeList();
    return out;
  }

  /* ---------- nav ---------- */
  function show(view) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    if (view === "reports") loadReports();
    if (view === "system") loadSystem();
  }
  $("#nav").addEventListener("click", (e) => { const b = e.target.closest(".tab"); if (b) show(b.dataset.view); });

  /* ---------- status pill ---------- */
  async function loadStatus() {
    const pill = $("#sys-pill"), txt = $("#sys-text");
    try {
      const s = await api("/api/status");
      pill.className = "sys ok";
      txt.textContent = `LLM: ${s.llm_provider}`;
      return s;
    } catch {
      pill.className = "sys bad";
      txt.textContent = "Backend unreachable";
    }
  }

  /* ---------- analyze ---------- */
  const textEl = $("#text"), titleEl = $("#title");
  const updateCount = () => { $("#count").textContent = `${textEl.value.trim().length} chars`; };
  textEl.addEventListener("input", updateCount);

  $("#clear").addEventListener("click", () => { textEl.value = ""; titleEl.value = ""; updateCount(); $("#results").innerHTML = ""; hideError(); });

  $("#file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    textEl.value = await f.text();
    if (!titleEl.value) titleEl.value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    updateCount();
    e.target.value = "";
  });

  async function loadSamples() {
    const box = $("#samples");
    try {
      const items = await api("/api/samples");
      if (!items.length) { box.innerHTML = '<span class="empty">No samples found</span>'; return; }
      box.innerHTML = items.map((s, i) => `<button class="sample" data-i="${i}">${esc(s.title)}</button>`).join("");
      box.onclick = (e) => {
        const b = e.target.closest(".sample");
        if (!b) return;
        const s = items[+b.dataset.i];
        titleEl.value = s.title;
        textEl.value = s.text;
        updateCount();
        textEl.scrollIntoView({ behavior: "smooth", block: "center" });
      };
    } catch (err) {
      box.innerHTML = `<span class="empty">${esc(err.message)}</span>`;
    }
  }

  function startLoading() { $("#loading").hidden = false; }
  function stopLoading() { $("#loading").hidden = true; }
  function showError(msg) { const e = $("#error"); e.hidden = false; e.innerHTML = `${esc(msg)}`; }
  function hideError() { $("#error").hidden = true; }

  $("#run").addEventListener("click", async () => {
    hideError();
    const text = textEl.value.trim();
    if (text.length < 30) return showError("Input must be at least 30 characters.");
    const btn = $("#run");
    btn.disabled = true;
    $("#results").innerHTML = "";
    startLoading();
    try {
      const report = await api("/api/analyze", { method: "POST", body: { title: titleEl.value.trim() || "Untitled Project", text } });
      renderReport(report, $("#results"));
      $("#results").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      showError(err.message);
    } finally {
      stopLoading();
      btn.disabled = false;
    }
  });

  /* ---------- report renderer ---------- */
  function renderReport(r, target) {
    const ra = r.requirements_analysis, s = r.sdlc_recommendation, pc = r.project_characteristics;
    const reqs = ra.requirements || [];
    const scores = Object.entries(s.model_scores || {}).sort((a, b) => b[1] - a[1]);
    const cats = [...new Set(reqs.map((x) => x.category))];
    const pris = ["Critical", "High", "Medium", "Low"].filter((p) => reqs.some((x) => x.priority === p));
    const slug = r._slug;

    target.innerHTML = `
      <div class="hero">
        <div><div class="lbl2">Recommended model</div><div class="model">${esc(s.recommended_model)}</div><div class="conf">${Math.round(s.confidence * 100)}% confidence</div></div>
        <div class="title">
          <h2>${esc(r.project_title)}</h2>
          <div class="meta">${esc(new Date(r.timestamp).toLocaleString())}${r._elapsed_seconds ? ` · ${r._elapsed_seconds}s` : ""}</div>
          <div class="actions">
            <button class="btn" data-dl="md">Download .md</button>
            <button class="btn" data-dl="json">Download .json</button>
          </div>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><div class="n">${reqs.length}</div><div class="l">Requirements</div></div>
        <div class="stat"><div class="n">${(ra.ambiguities || []).length}</div><div class="l">Ambiguities</div></div>
        <div class="stat"><div class="n">${(ra.conflicts || []).length}</div><div class="l">Conflicts</div></div>
        <div class="stat"><div class="n">${(ra.missing_information || []).length}</div><div class="l">Missing info</div></div>
        <div class="stat"><div class="n sm">${esc(pc.risk_level)}</div><div class="l">Risk</div></div>
        <div class="stat"><div class="n sm">${esc(pc.estimated_size)}</div><div class="l">Size</div></div>
      </div>

      <div class="card">
        <h3 class="h-sub">Model scores</h3>
        <div class="scores">
          ${scores.map(([n, v]) => `<div class="score ${n === s.recommended_model ? "win" : ""}"><span class="nm">${esc(n)}</span><div class="track"><div class="fill" data-w="${Math.max(0, Math.min(100, v))}"></div></div><span class="v">${v.toFixed(1)}</span></div>`).join("")}
        </div>
      </div>

      <div class="rtabs" id="rtabs">
        <button class="rtab active" data-p="reqs">Requirements<span class="pill">${reqs.length}</span></button>
        <button class="rtab" data-p="issues">Issues<span class="pill">${(ra.ambiguities || []).length + (ra.conflicts || []).length + (ra.missing_information || []).length}</span></button>
        <button class="rtab" data-p="compliance">Compliance<span class="pill">${(r.compliance_report?.checks || []).length}</span></button>
        <button class="rtab" data-p="sdlc">SDLC Determiner</button>
        <button class="rtab" data-p="trace">Traceability<span class="pill">${(r.traceability_matrix || []).length}</span></button>
        <button class="rtab" data-p="raw">Full report</button>
      </div>

      <div class="rpane active" data-p="reqs">
        <div class="agent-heading"><span>Agent 1</span><b>Requirement Analyser</b><em>Completed</em></div>
        <div class="req-summary">
          <div class="req-summary-card functional">
            <div class="req-summary-title">Functional Requirements</div>
            <div class="req-summary-count">${reqs.filter(x => x.category === "Functional").length}</div>
            <div class="req-summary-help">What the banking system must do</div>
          </div>
          <div class="req-summary-card nonfunctional">
            <div class="req-summary-title">Non-Functional Requirements</div>
            <div class="req-summary-count">${reqs.filter(x => x.category === "Non-functional").length}</div>
            <div class="req-summary-help">How well the system must operate</div>
          </div>
        </div>
        <section class="req-section">
          <div class="req-section-head"><h3>Functional Requirements</h3><span class="section-count">${reqs.filter(x => x.category === "Functional").length}</span></div>
          <div class="req-section-list">${reqs.filter(x => x.category === "Functional").map(reqCard).join("") || '<div class="empty">No functional requirements extracted.</div>'}</div>
        </section>
        <section class="req-section">
          <div class="req-section-head"><h3>Non-Functional Requirements</h3><span class="section-count">${reqs.filter(x => x.category === "Non-functional").length}</span></div>
          <div class="req-section-list">${reqs.filter(x => x.category === "Non-functional").map(reqCard).join("") || '<div class="empty">No non-functional requirements extracted.</div>'}</div>
        </section>
        <section class="req-section other-reqs">
          <div class="req-section-head"><h3>Other Analysed Requirements</h3><span class="section-count">${reqs.filter(x => x.category !== "Functional" && x.category !== "Non-functional").length}</span></div>
          <div class="filters" id="filters">
            <button class="chip on" data-f="all">All</button>
            ${pris.map((p) => `<button class="chip" data-f="pri:${esc(p)}">${esc(p)}</button>`).join("")}
            ${cats.filter(c => c !== "Functional" && c !== "Non-functional").map((c) => `<button class="chip" data-f="cat:${esc(c)}">${esc(c)}</button>`).join("")}
          </div>
          <div id="reqlist">${reqs.filter(x => x.category !== "Functional" && x.category !== "Non-functional").map(reqCard).join("") || '<div class="empty">No additional requirement categories.</div>'}</div>
        </section>
      </div>

      <div class="rpane" data-p="issues">${issuesPane(ra)}</div>
      <div class="rpane" data-p="compliance"><div class="agent-heading"><span>Agent 2</span><b>Compliance Agent</b><em>Completed</em></div>${compliancePane(r.compliance_report)}</div>
      <div class="rpane" data-p="sdlc"><div class="agent-heading"><span>Agent 3</span><b>SDLC Determiner</b><em>Completed</em></div>${sdlcPane(s)}</div>
      <div class="rpane" data-p="trace">${tracePane(r.traceability_matrix || [])}</div>
      <div class="rpane" data-p="raw"><div class="prose">${md(r.summary_markdown)}</div></div>
    `;

    // animate score bars
    requestAnimationFrame(() => requestAnimationFrame(() => $$(".fill", target).forEach((f) => (f.style.width = f.dataset.w + "%"))));

    // tabs
    $("#rtabs", target).addEventListener("click", (e) => {
      const b = e.target.closest(".rtab"); if (!b) return;
      $$(".rtab", target).forEach((x) => x.classList.toggle("active", x === b));
      $$(".rpane", target).forEach((x) => x.classList.toggle("active", x.dataset.p === b.dataset.p));
    });

    // requirement expand + filters
    $("#reqlist", target).addEventListener("click", (e) => {
      const h = e.target.closest(".req-head"); if (h) h.parentElement.classList.toggle("open");
    });
    $("#filters", target).addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      $$(".chip", target).forEach((x) => x.classList.toggle("on", x === c));
      const f = c.dataset.f;
      $$(".req", target).forEach((el) => {
        el.style.display = f === "all" || (f.startsWith("pri:") && el.dataset.pri === f.slice(4)) || (f.startsWith("cat:") && el.dataset.cat === f.slice(4)) ? "" : "none";
      });
    });

    // downloads
    $$("[data-dl]", target).forEach((b) => b.addEventListener("click", () => {
      const isMd = b.dataset.dl === "md";
      const blob = new Blob([isMd ? r.summary_markdown : JSON.stringify(r, null, 2)], { type: isMd ? "text/markdown" : "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${slug || "report"}_report.${isMd ? "md" : "json"}`;
      a.click();
      URL.revokeObjectURL(a.href);
    }));
  }

  function reqCard(q) {
    const conf = Math.round((q.confidence ?? 0) * 100);
    const originLabel = q.is_explicit ? "Explicit" : "Domain-derived";
    return `<div class="req p-${esc(q.priority)}" data-pri="${esc(q.priority)}" data-cat="${esc(q.category)}">
      <div class="req-head">
        <span class="rid">${esc(q.id)}</span>
        <span class="rtitle">${esc(q.description)} <span class="req-origin">(${esc(originLabel)})</span></span>
        <span class="badge">${esc(q.category)}</span>
        <span class="badge">${esc(q.priority)}</span>
      </div>
      <div class="req-body">
        <div class="kv"><b>Requirement</b>${esc(q.description)} <span class="req-origin">(${esc(originLabel)})</span></div>
        <div class="kv"><b>Rationale</b>${esc(q.explanation)}</div>
        <div class="kv"><b>Source</b>${esc(q.source_reference)}</div>
        <div class="kv"><b>Confidence</b>${conf}%<span class="confbar"><i style="width:${conf}%"></i></span></div>
        ${q.supporting_passage ? `<div class="kv"><b>Supporting passage</b><div class="passage">${esc(q.supporting_passage)}</div></div>` : ""}
      </div>
    </div>`;
  }

  function issuesPane(ra) {
    const amb = ra.ambiguities || [], con = ra.conflicts || [], mis = ra.missing_information || [];
    let h = "";
    h += `<h3 class="pane-h">Ambiguities</h3>` + (amb.length ? amb.map((a) => `<div class="issue"><h4>${esc(a.requirement_id || "General")}</h4><div class="quote">${esc(a.problematic_text)}</div><p>${esc(a.issue)}</p><p><b>Fix:</b> ${esc(a.suggested_clarification)}</p></div>`).join("") : '<div class="empty">None.</div>');
    h += `<h3 class="pane-h">Conflicts</h3>` + (con.length ? con.map((c) => `<div class="issue"><h4>${(c.conflicting_requirement_ids || []).map(esc).join(" / ")} <span class="badge">${esc(c.severity)}</span></h4><p>${esc(c.description)}</p><p><b>Resolution:</b> ${esc(c.resolution_recommendation)}</p></div>`).join("") : '<div class="empty">None.</div>');
    h += `<h3 class="pane-h">Missing information</h3>` + (mis.length ? mis.map((m) => `<div class="issue"><h4>${esc(m.area)}</h4><p>${esc(m.description)}</p><p><b>Impact:</b> ${esc(m.potential_impact)}</p></div>`).join("") : '<div class="empty">None.</div>');
    return h;
  }

  function sdlcPane(s) {
    let h = `<div class="sdlc-result"><div class="sdlc-label">Recommended SDLC Model</div><div class="sdlc-model">${esc(s.recommended_model)}</div></div>`;
    h += `<section class="req-section"><div class="req-section-head"><h3>Rationale</h3></div><div class="card prose-lite">${md(s.explanation)}</div></section>`;
    if ((s.factors_considered || []).length) {
      h += `<section class="req-section"><div class="req-section-head"><h3>SDLC-Relevant Factors</h3><span class="section-count">${s.factors_considered.length}</span></div><div class="factor-list">` +
        s.factors_considered.map((f) => `<div class="factor-card"><div class="factor-name">${esc(f.factor_name)}</div><div class="factor-level">${esc(f.assessment_level)}</div><div class="factor-evidence">${esc(f.evidence)}</div></div>`).join("") + `</div></section>`;
    }
    if ((s.supporting_evidence || []).length) {
      h += `<section class="req-section"><div class="req-section-head"><h3>Matched Project Factors</h3><span class="section-count">${s.supporting_evidence.length}</span></div><ul class="point-list">${s.supporting_evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>`;
    }
    return h;
  }

  function compliancePane(c) {
    if (!c) return '<div class="empty">Compliance report not available.</div>';
    let h = `<div class="compliance-summary"><div><b>Compliance Summary</b><p>${esc(c.summary)}</p></div><div class="compliance-stats"><span>${c.compliant_count} Compliant</span><span>${c.needs_review_count} Needs Review</span><span>${c.domain_derived_count} Domain-derived</span></div></div>`;
    h += `<section class="req-section"><div class="req-section-head"><h3>Verified Requirements Against Regulatory DB</h3><span class="section-count">${(c.checks || []).length}</span></div><div class="compliance-list">`;
    h += (c.checks || []).map((x, i) => `<div class="compliance-item"><div class="compliance-title"><span class="check-num">${i + 1}</span><span>${esc(x.requirement)}</span><span class="status">${esc(x.status)}</span></div><div class="compliance-body"><div><b>Evidence:</b> ${esc(x.evidence || "—")}</div><div><b>Notes:</b> ${esc(x.notes || "—")}</div><div><b>Standard:</b> ${esc(x.standard || "—")}${x.section ? ` · <b>Section:</b> ${esc(x.section)}` : ""}</div></div></div>`).join("");
    h += `</div></section>`;
    return h;
  }

  function tracePane(t) {
    if (!t.length) return '<div class="empty">None.</div>';
    return `<div class="tablewrap"><table class="trace"><thead><tr><th>Requirement</th><th>Origin</th><th>Standard</th><th>Clause</th><th>SDLC phase</th><th>Status</th></tr></thead><tbody>` +
      t.map((x) => `<tr><td>${esc(x.requirement_id)}</td><td>${esc(x.origin)}</td><td>${esc(x.regulatory_standard || "Stakeholder specification")}</td><td>${esc(x.clause_or_section || "—")}</td><td>${esc(x.sdlc_phase)}</td><td class="${x.validation_status.startsWith("Passed") ? "st-ok" : "st-warn"}">${esc(x.validation_status)}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }

  /* ---------- reports archive ---------- */
  async function loadReports() {
    const box = $("#report-list");
    box.innerHTML = '<div class="inline-load">Loading…</div>';
    try {
      const rows = await api("/api/reports");
      if (!rows.length) { box.innerHTML = '<div class="empty">No reports yet.</div>'; return; }
      box.innerHTML = rows.map((r) => `<button class="rcard" data-slug="${esc(r.slug)}">
        <div class="t">${esc(r.title)}</div>
        <div class="m">${esc(r.timestamp ? new Date(r.timestamp).toLocaleString() : "")}<br>${r.requirements} requirements · ${Math.round(r.confidence * 100)}%</div>
        <span class="mod">${esc(r.model)}</span></button>`).join("");
      box.onclick = async (e) => {
        const c = e.target.closest(".rcard"); if (!c) return;
        const detail = $("#report-detail");
        detail.innerHTML = '<div class="inline-load">loading…</div>';
        try {
          const rep = await api(`/api/reports/${encodeURIComponent(c.dataset.slug)}`);
          rep._slug = c.dataset.slug;
          renderReport(rep, detail);
          detail.scrollIntoView({ behavior: "smooth" });
        } catch (err) { detail.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
      };
    } catch (err) {
      box.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    }
  }

  /* ---------- knowledge search ---------- */
  async function doSearch() {
    const q = $("#q").value.trim();
    const out = $("#kb-results"), ld = $("#kb-loading");
    if (q.length < 3) { out.innerHTML = '<div class="error">Enter a longer query.</div>'; return; }
    out.innerHTML = ""; ld.hidden = false; $("#qgo").disabled = true;
    try {
      const hits = await api("/api/search", { method: "POST", body: { query: q, top_k: 6, source_type: $("#qtype").value || null } });
      const terms = [...new Set(q.toLowerCase().match(/[a-z0-9\-]{4,}/g) || [])];
      const hl = (t) => { let s = esc(t); terms.forEach((w) => { s = s.replace(new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>"); }); return s; };
      out.innerHTML = hits.length ? hits.map((h, i) => `<div class="hit"><div class="hh"><span class="doc">#${i + 1} ${esc(h.doc_name || h.doc_id)}</span><span class="sc">${esc(h.source_type)} · score ${h.score}</span></div>
        <div class="sec">${esc(h.section_title)}${h.clause_id ? ` · clause ${esc(h.clause_id)}` : ""}</div>
        <div class="passage">${hl(h.content)}</div></div>`).join("") : '<div class="empty">No results.</div>';
    } catch (err) {
      out.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    } finally { ld.hidden = true; $("#qgo").disabled = false; }
  }
  $("#qgo").addEventListener("click", doSearch);
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

  /* ---------- eval ---------- */
  $("#evalgo").addEventListener("click", async () => {
    const out = $("#eval-results"), ld = $("#eval-loading"), btn = $("#evalgo");
    out.innerHTML = ""; ld.hidden = false; btn.disabled = true;
    try {
      const e = await api("/api/evaluate", { method: "POST" });
      const pct = (x) => `${(x * 100).toFixed(1)}%`;
      out.innerHTML = `<div class="stats" style="margin-top:1.2rem">
        <div class="stat"><div class="n">${e.test_cases_count}</div><div class="l">Test cases</div></div>
        <div class="stat"><div class="n">${pct(e.hit_rate_at_1)}</div><div class="l">Hit rate @1</div></div>
        <div class="stat"><div class="n">${pct(e.hit_rate_at_k)}</div><div class="l">Hit rate @K</div></div>
        <div class="stat"><div class="n">${e.mrr.toFixed(3)}</div><div class="l">MRR</div></div>
        <div class="stat"><div class="n">${pct(e.avg_top1_answerability)}</div><div class="l">Top-1 answerability</div></div>
        <div class="stat"><div class="n">${pct(e.avg_best_answerability)}</div><div class="l">Best answerability</div></div></div>
        <div class="tablewrap"><table class="trace"><thead><tr><th>Query</th><th>Target</th><th>First hit</th><th>Top-1</th><th>Best</th><th>Result</th></tr></thead><tbody>${(e.case_results || []).map((c) => `<tr><td>${esc(c.query)}</td><td>${esc(c.target_doc)}</td><td>${c.first_hit_rank ?? "—"}</td><td>${pct(c.top1_answerability)}</td><td>${pct(c.best_answerability)}</td><td class="${c.passed ? "pass" : "fail"}">${c.passed ? "Pass" : "Fail"}</td></tr>`).join("")}</tbody></table></div>`;
    } catch (err) {
      out.innerHTML = `<div class="error">${esc(err.message)}</div>`;
    } finally { ld.hidden = true; btn.disabled = false; }
  });

  /* ---------- system ---------- */
  async function loadSystem() {
    const g = $("#sys-grid");
    try {
      const s = await api("/api/status");
      g.innerHTML = [
        ["LLM provider", s.llm_provider], ["LLM model", s.llm_model], ["Embeddings", s.embedding_model], ["Reranker", s.reranker],
        ["Source docs", s.rag_docs], ["Saved reports", s.reports], ["Engine loaded", s.engine_loaded ? "Yes" : "Not yet"],
      ].map(([l, n]) => `<div class="stat"><div class="n sm">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");
    } catch (err) { g.innerHTML = `<div class="error">${esc(err.message)}</div>`; }
  }

  async function ingest(force) {
    const out = $("#ingest-out");
    out.hidden = false; out.textContent = "Working…";
    $("#ingest").disabled = $("#ingest-force").disabled = true;
    try { out.textContent = JSON.stringify(await api("/api/ingest", { method: "POST", body: { force } }), null, 2); }
    catch (err) { out.textContent = "Error: " + err.message; }
    finally { $("#ingest").disabled = $("#ingest-force").disabled = false; }
  }
  $("#ingest").addEventListener("click", () => ingest(false));
  $("#ingest-force").addEventListener("click", () => ingest(true));

  /* ---------- boot ---------- */
  loadStatus();
  loadSamples();
  updateCount();
})();
