(function () {
  const D = (id) => dash.data(id);
  const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const dt = (s) => { const d = new Date(s); return isNaN(d) ? '—' : new Intl.DateTimeFormat('de-DE', {dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Berlin'}).format(d); };
  const link = (href, text) => { const a = mk('a', null, text); if (/^https:\/\/github\.com\//.test(href || '')) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; } return a; };
  const open = (i) => i.status !== 'Fertig' && i.status !== 'Geschlossen';
  const STATUS_ORDER = ['In Arbeit', 'Geplant', 'Parkplatz', 'Fertig', 'Unklar'];
  const STATUS_CLS = {'Fertig': 's-done', 'In Arbeit': 's-you', 'Geplant': 's-ready', 'Parkplatz': '', 'Unklar': 's-bad', 'Blockiert': 's-block', 'Bereit': 's-ready', 'Offen': 's-ready', 'In Review': 's-review'};
  const STATUS_COL = {'Fertig': 'c-green', 'In Arbeit': 'c-orange', 'Geplant': 'c-blue', 'Parkplatz': 'c-purple', 'Unklar': 'c-red'};
  const pill = (s) => mk('span', 'ag-pill ' + (STATUS_CLS[s] || ''), s);
  const REPO = 'https://github.com/castorsalzmann-ui/AbeltonGod';

  // ---- calcs (one place for every derived number) ----
  dash.calc('feat_counts', {
    inputs: ['features'], title: 'Features je Status', description: 'Anzahl Features je Status aus docs/ROADMAP.md.',
    fn: (features) => { const m = {}; features.forEach((f) => { m[f.status] = (m[f.status] || 0) + 1; }); return Object.keys(m).map((status) => ({status, n: m[status]})); }
  });
  dash.calc('you_items', {
    inputs: ['user_actions'], title: 'Wartet auf dich', description: 'Offene Aufgaben für dich aus docs/WAITING_ON_USER.md und offene PRs.',
    fn: (user_actions) => user_actions.filter((a) => a.state === 'open')
      .map((a) => ({key: a.url || a.task, kind: a.kind, number: a.number, title: a.title, task: a.task, url: a.url, since: a.since}))
  });
  dash.calc('you_count', {
    inputs: ['you_items'], title: 'Anzahl wartet auf dich', description: 'Zahl der offenen Punkte, die auf dich warten.',
    fn: (you_items) => [{n: you_items.length}]
  });
  dash.calc('open_work', {
    inputs: ['issues'], title: 'Offene Issues und PRs', description: 'Alle nicht erledigten Issues und PRs.',
    fn: (issues) => issues.filter((i) => i.status !== 'Fertig' && i.status !== 'Geschlossen')
  });
  dash.calc('gate_recent', {
    inputs: ['gate'], title: 'Letzte Gate-Läufe', description: 'Die acht neuesten Läufe aus dem Gate-Verlauf.',
    fn: (gate) => gate.slice().sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 8)
  });
  dash.calc('gate_latest', {
    inputs: ['gate_recent'], title: 'Neuester Gate-Lauf', description: 'Der neueste Lauf aus dem Gate-Verlauf.',
    fn: (gate_recent) => gate_recent.slice(0, 1)
  });
  dash.calc('cap_counts', {
    inputs: ['capabilities'], title: 'Ableton-Funktionen je Status', description: 'Anzahl der Funktionen je Status aus contracts/capabilities.json.',
    fn: (capabilities) => { const m = {}; capabilities.forEach((c) => { m[c.status] = (m[c.status] || 0) + 1; }); return Object.keys(m).map((status) => ({status, n: m[status]})); }
  });

  // ---- tabs ----
  const tabs = Array.from(document.querySelectorAll('.ag-tab'));
  const show = (name) => {
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t.dataset.tab === name)));
    document.querySelectorAll('.ag-sec').forEach((s) => { s.hidden = s.id !== name; });
  };
  tabs.forEach((t) => t.addEventListener('click', () => show(t.dataset.tab)));

  // ---- state for filters ----
  let featSel = '', workSel = '', resQ = '';
  const chips = (host, values, get, set) => {
    host.replaceChildren();
    ['', ...values].forEach((v) => {
      const b = mk('button', 'ag-chip', v || 'Alle'); b.setAttribute('aria-pressed', String(get() === v));
      b.addEventListener('click', () => { set(v); render(); }); host.appendChild(b);
    });
  };
  document.getElementById('res_q').addEventListener('input', (e) => { resQ = e.target.value.toLowerCase(); render(); });

  const tile = (host, label, n, cls, calc, status) => {
    const t = mk('div', 'ag-tile ' + cls);
    t.appendChild(mk('div', 'ag-lbl', label));
    const num = mk('div', 'ag-num', String(n));
    num.setAttribute('data-source', calc); num.setAttribute('data-field', 'n'); num.setAttribute('data-where', 'status=' + encodeURIComponent(status));
    t.appendChild(num); host.appendChild(t);
  };
  const row = (tbody, key, cells) => {
    const tr = mk('tr'); tr.setAttribute('data-key', key);
    cells.forEach((c) => { const td = mk('td'); if (c instanceof Node) td.appendChild(c); else td.textContent = c == null ? '' : String(c); tr.appendChild(td); });
    tbody.appendChild(tr);
  };
  const emptyRow = (tbody, cols, text) => { const tr = mk('tr'); const td = mk('td', null, text); td.colSpan = cols; tr.appendChild(td); tbody.appendChild(tr); };
  const note = (id, text) => { const e = document.getElementById(id); if (e) e.textContent = text; };

  function render() {
    const f = D('features'), r = D('research'), iss = D('issues'), ph = D('phases'), pl = D('pipeline');
    const fc = D('feat_counts'), yi = D('you_items'), ow = D('open_work'), gr = D('gate_recent'), cc = D('cap_counts');

    // header note
    const snap = D('snapshot');
    const banner = document.getElementById('age_banner');
    const at = snap.status === 'ok' && snap.data[0] ? new Date(snap.data[0].at).getTime() : NaN;
    if (!isNaN(at)) {
      const age = (Date.now() - at) / 36e5;
      const el = document.getElementById('h_at'); if (el) el.textContent = dt(snap.data[0].at);
      note('h_note', 'Momentaufnahme aus GitHub und dem Repo, wird automatisch alle 30 Minuten erneuert.');
      if (banner) {
        const txt = age < 1 ? `${Math.max(0, Math.round(age * 60))} Minuten` : `${Math.round(age * 10) / 10} Stunden`;
        banner.textContent = age > 2 ? `Achtung: Die Daten sind ${txt} alt (Stand ${dt(snap.data[0].at)}). Die automatische Aktualisierung scheint zu haken.` : `Daten von vor ${txt} (Stand ${dt(snap.data[0].at)}).`;
        banner.classList.toggle('stale', age > 2);
      }
    } else if (banner && snap.status !== 'loading') {
      banner.textContent = 'Achtung: Kein Datenstand gefunden, die Seite zeigt möglicherweise nichts Aktuelles.';
      banner.classList.add('stale');
    }

    // overview tiles
    const tiles = document.getElementById('feat_tiles'); tiles.replaceChildren();
    if (fc.status === 'ok') {
      STATUS_ORDER.forEach((s) => { const x = fc.data.find((d) => d.status === s); if (x) tile(tiles, s, x.n, STATUS_COL[s] || '', 'feat_counts', s); });
    }
    const yl = document.getElementById('you_list'); yl.replaceChildren();
    if (yi.status === 'ok') {
      if (!yi.data.length) yl.appendChild(mk('li', 'ag-empty', 'Für dich gibt es gerade nichts zu tun.'));
      yi.data.forEach((i) => {
        const li = mk('li', 'ag-item'); li.setAttribute('data-key', i.key);
        li.appendChild(mk('div', 'ag-rank', i.kind.slice(0, 1)));
        const box = mk('div'); const t = mk('div', 'ag-t'); t.appendChild(mk('b', null, i.kind + ': '));
        t.appendChild(document.createTextNode(i.task + ' '));
        if (i.url) t.appendChild(link(i.url, i.number ? '→ #' + i.number : '→ Link'));
        box.appendChild(t);
        const m = mk('div', 'ag-m'); if (i.title) m.appendChild(mk('span', null, i.title)); if (i.since) m.appendChild(mk('span', null, 'seit ' + i.since)); box.appendChild(m);
        li.appendChild(box); yl.appendChild(li);
      });
    } else if (yi.status === 'error') { yl.appendChild(mk('li', 'ag-fail', 'Konnte nicht geladen werden')); }
    const al = document.getElementById('active_list'); al.replaceChildren();
    const aw = D('active_work');
    if (aw.status === 'ok') {
      if (!aw.data.length) al.appendChild(mk('li', 'ag-empty', 'Laut GitHub arbeitet gerade niemand (kein Issue mit „in progress“, kein offener PR).'));
      aw.data.slice(0, 12).forEach((w) => {
        const li = mk('li', 'ag-item'); li.setAttribute('data-key', w.url);
        li.appendChild(mk('div', 'ag-rank', String(w.role).slice(0, 2).toUpperCase()));
        const box = mk('div'); const t = mk('div', 'ag-t'); t.appendChild(link(w.url, `${w.kind} ${w.number}: ${w.title}`)); box.appendChild(t);
        const m = mk('div', 'ag-m'); m.appendChild(mk('span', null, w.role)); m.appendChild(mk('span', null, w.status)); m.appendChild(mk('span', null, 'aktualisiert ' + dt(w.updated))); box.appendChild(m);
        li.appendChild(box); al.appendChild(li);
      });
    }
    const tl = document.getElementById('track_list'); tl.replaceChildren();
    if (pl.status === 'ok') {
      pl.data.forEach((t) => {
        const li = mk('li', 'ag-item'); li.appendChild(mk('div', 'ag-rank', t.track));
        const box = mk('div'); box.appendChild(mk('div', 'ag-t', `${t.phase}: ${t.goal}`)); box.appendChild(mk('div', 'ag-m', t.status));
        li.appendChild(box); tl.appendChild(li);
      });
    }

    // roadmap
    chips(document.getElementById('feat_filter'), STATUS_ORDER, () => featSel, (v) => { featSel = v; });
    const fr = document.getElementById('feat_rows'); fr.replaceChildren();
    if (f.status === 'ok') {
      const rows = f.data.filter((x) => !featSel || x.status === featSel)
        .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status));
      if (!rows.length) emptyRow(fr, 5, 'Keine Features mit diesem Status.');
      rows.forEach((x) => {
        const names = Array.isArray(x.research) ? x.research : String(x.research || '').split(',').map((s) => s.trim()).filter(Boolean);
        const rc = mk('div');
        if (!names.length) rc.textContent = 'Keine Notiz';
        names.forEach((n, k) => { if (k) rc.appendChild(document.createTextNode(' · ')); rc.appendChild(link(`${REPO}/blob/main/docs/research/${n}`, n.replace(/^\d{4}-\d{2}-\d{2}_/, '').replace(/\.md$/, ''))); });
        row(fr, x.feature, [x.feature, x.phase, pill(x.status), rc, x.work]);
      });
    }
    const pr = document.getElementById('phase_rows'); pr.replaceChildren();
    if (ph.status === 'ok') ph.data.forEach((p) => row(pr, p.phase, [p.phase, p.name, p.goal, pill(p.status), `${p.criteria_met}/${p.criteria_total}`]));

    // research
    const rr = document.getElementById('res_rows'); rr.replaceChildren();
    if (r.status === 'ok') {
      const rows = r.data.filter((x) => !resQ || `${x.title} ${(x.features || []).join(' ')}`.toLowerCase().includes(resQ));
      if (!rows.length) emptyRow(rr, 4, 'Keine Notiz gefunden.');
      rows.forEach((x) => {
        const feats = Array.isArray(x.features) ? x.features : String(x.features || '').split(',').map((s) => s.trim()).filter(Boolean);
        row(rr, x.file, [x.date, link(x.url, x.title), x.mapped && feats.length ? feats.join(' · ') : 'Nicht zugeordnet', x.words]);
      });
    }

    // work
    const ws = ['In Arbeit', 'In Review', 'Blockiert', 'Bereit', 'Offen'];
    chips(document.getElementById('work_filter'), ws, () => workSel, (v) => { workSel = v; });
    const wr = document.getElementById('work_rows'); wr.replaceChildren();
    if (ow.status === 'ok') {
      const rows = ow.data.filter((x) => !workSel || x.status === workSel)
        .sort((a, b) => ws.indexOf(a.status) - ws.indexOf(b.status) || b.number - a.number);
      if (!rows.length) emptyRow(wr, 5, 'Nichts offen mit diesem Status.');
      rows.forEach((x) => row(wr, x.number, [link(x.url, String(x.number)), x.title, pill(x.status), x.owner, x.track]));
    }

    // quality
    const gr2 = document.getElementById('gate_rows'); gr2.replaceChildren();
    if (gr.status === 'ok') gr.data.forEach((g) => row(gr2, g.run, [dt(g.date), g.run, g.passed, g.skipped, g.failed, g.ruff]));
    const ct = document.getElementById('cap_tiles'); ct.replaceChildren();
    if (cc.status === 'ok') {
      const CO = {tested: ['tested', 'c-green'], supported: ['supported', 'c-blue'], unknown: ['unknown', 'c-yellow'], unsupported: ['unsupported', 'c-red']};
      Object.keys(CO).forEach((s) => { const x = cc.data.find((d) => d.status === s); if (x) tile(ct, CO[s][0], x.n, CO[s][1], 'cap_counts', s); });
    }
  }
  dash.onData(render);
})();
