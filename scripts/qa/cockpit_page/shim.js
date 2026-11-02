/* Static-site stand-in for the claude.ai artifact runtime: window.dash with data(), calc(), onData().
   Raw datasets come from data/<id>.json (fetch) or, when fetch is blocked (file://), from
   window.COCKPIT_DATA embedded by the builder. Also fills elements marked
   data-source/data-field[/data-row][/data-where=field=value], as the artifact runtime does. */
(function () {
  const raw = {};      // id -> {status, data}
  const calcs = {};    // id -> {inputs, fn}
  const listeners = [];
  const embedded = window.COCKPIT_DATA || {};

  function get(id) {
    if (calcs[id]) {
      const c = calcs[id];
      const ins = c.inputs.map(get);
      const bad = ins.find((i) => i.status === 'error');
      if (bad) return {status: 'error', data: []};
      if (ins.some((i) => i.status !== 'ok')) return {status: 'loading', data: []};
      try { return {status: 'ok', data: c.fn(...ins.map((i) => i.data))}; } catch (e) { return {status: 'error', data: [], error: String(e)}; }
    }
    if (!raw[id]) { raw[id] = {status: 'loading', data: []}; load(id); }
    return raw[id];
  }

  function done(id, state) {
    raw[id] = state;
    notify();
  }

  function load(id) {
    const fallback = () => (Array.isArray(embedded[id]) ? done(id, {status: 'ok', data: embedded[id]}) : done(id, {status: 'error', data: []}));
    let p;
    try { p = fetch('data/' + id + '.json', {cache: 'no-store'}); } catch (e) { return fallback(); }
    p.then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((rows) => done(id, Array.isArray(rows) ? {status: 'ok', data: rows} : {status: 'error', data: []}))
      .catch(fallback);
  }

  function bind() {
    document.querySelectorAll('[data-source][data-field]:not([data-row-key])').forEach((el) => {
      const d = get(el.dataset.source);
      if (d.status !== 'ok') return;
      let rows = d.data;
      if (el.dataset.where) {
        const i = el.dataset.where.indexOf('=');
        const k = el.dataset.where.slice(0, i), v = decodeURIComponent(el.dataset.where.slice(i + 1));
        rows = rows.filter((r) => String(r[k]) === v);
      }
      const r = rows[Number(el.dataset.row || 0)];
      if (r && r[el.dataset.field] != null) el.textContent = String(r[el.dataset.field]);
    });
  }

  let pending = false;
  function notify() {
    if (pending) return;
    pending = true;
    Promise.resolve().then(() => { pending = false; listeners.forEach((f) => f()); bind(); });
  }

  window.dash = {
    data: get,
    calc: (id, spec) => { calcs[id] = {inputs: spec.inputs, fn: spec.fn}; },
    onData: (f) => { listeners.push(f); notify(); },
  };
})();
