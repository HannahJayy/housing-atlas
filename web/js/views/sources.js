// Data sources, update controls, weekly schedule and settings.

import { api, post, clearCache } from '../api.js';
import { h, clear, toast } from '../ui.js';
import { STATE, metric } from '../fmt.js';
import { APP, pollUpdate, refreshMeta } from '../app.js';

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function bytes(n) {
  if (!n) return '';
  if (n > 1e9) return (n / 1e9).toFixed(1) + ' GB';
  if (n > 1e6) return (n / 1e6).toFixed(1) + ' MB';
  if (n > 1e3) return (n / 1e3).toFixed(0) + ' KB';
  return n + ' B';
}

// "Open on your phone": the addresses phones can use, and a switch to allow it (saved immediately).
function phoneCard(canAdmin) {
  const ph = (STATE.meta && STATE.meta.phone) || { enabled: false, urls: [], saved_host: '127.0.0.1' };
  const card = h('div', { class: 'card' }, h('h2', null, 'Open on your phone'));
  if (ph.enabled && ph.urls.length) {
    card.appendChild(h('p', { class: 'small secondary' }, 'On your phone or tablet, type this address into the browser. This computer has to be on, with Housing Atlas running.'));
    for (const u of ph.urls) {
      card.appendChild(h('div', { style: { margin: '8px 0' } },
        h('div', { class: 'formula', style: { fontSize: '18px', userSelect: 'all', display: 'inline-block' } }, u.url),
        h('div', { class: 'small muted' }, u.kind === 'tailscale' ? 'From anywhere, with Tailscale on both devices' : 'On the same Wi-Fi')));
    }
    card.appendChild(h('p', { class: 'small muted' }, 'Tip: in your phone’s browser use Share › Add to Home Screen (iPhone) or ⋮ › Add to Home screen (Android) to get an app icon.'));
  } else if (ph.enabled) {
    card.appendChild(h('p', { class: 'small secondary' }, 'Phones on your Wi-Fi can connect: open http://<this computer’s IP address>:' + location.port + ' on your phone.'));
  } else {
    card.appendChild(h('p', { class: 'small secondary' }, 'Phone access is off right now, so only this computer can open Housing Atlas.'));
  }
  if (!canAdmin) return card;
  const box = h('input', { type: 'checkbox', checked: ph.saved_host === '0.0.0.0' ? true : null, onchange: async () => {
    try {
      await post('/api/settings', { server: { host: box.checked ? '0.0.0.0' : '127.0.0.1' } });
      ph.saved_host = box.checked ? '0.0.0.0' : '127.0.0.1';
      toast(box.checked === ph.enabled ? 'Saved' : 'Saved – now close the Housing Atlas window and start it again');
    } catch (e) { box.checked = !box.checked; toast(e.message); }
  } });
  card.appendChild(h('label', { class: 'row', style: { flexWrap: 'nowrap', alignItems: 'flex-start', gap: '8px', marginTop: '10px' } },
    box, h('span', null, 'Let phones and tablets on my Wi-Fi open Housing Atlas',
      h('span', { class: 'small muted', style: { display: 'block' } }, 'Takes effect the next time you start Housing Atlas. Only turn this on at home, not on public Wi-Fi.'))));
  return card;
}

export async function render(root) {
  const page = h('div', { class: 'page' });
  root.appendChild(page);
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Data & Sources'),
    h('p', null, window.HA_STATIC ? 'Where every number comes from and when it was last downloaded. All sources are free and public.'
      : 'Where every number comes from, when it was last downloaded, and controls to refresh it. All sources are free and public.'))));
  const updBox = h('div', { class: 'card' });
  const listBox = h('div');
  const otherBox = h('div');
  const settingsBox = h('div');
  const canAdmin = APP.meta && APP.meta.can_admin;
  if (window.HA_STATIC) page.append(updBox, listBox, otherBox, settingsBox);
  else page.append(updBox, h('div', { style: { marginTop: '14px' } }, phoneCard(canAdmin)), listBox, otherBox, settingsBox);
  let data = null;
  let timer = null;

  async function load() {
    try { data = await api('/api/sources'); } catch (e) { clear(updBox).appendChild(h('p', null, e.message)); return; }
    drawUpdate();
    drawList();
    drawOther();
  }

  function drawUpdate() {
    const u = data.update;
    clear(updBox);
    if (window.HA_STATIC) {
      updBox.appendChild(h('div', { class: 'card-head' }, h('div', null, h('h2', null, 'Data in this web version'),
        h('div', { class: 'sub' }, 'Last data update: ' + (data.last_update || '–') + ' · web copy built ' + (window.HA_STATIC.built || '')))));
      updBox.appendChild(h('p', { class: 'small secondary' }, 'This copy is read-only. To refresh it, run ',
        h('span', { class: 'formula' }, 'python app.py update'), ' and then ', h('span', { class: 'formula' }, 'python app.py export-static'),
        ' on the computer that has Housing Atlas installed (or use the local website, which refreshes itself every week).'));
      return;
    }
    updBox.appendChild(h('div', { class: 'card-head' }, h('div', null, h('h2', null, 'Update data'),
      h('div', { class: 'sub' }, 'Last full update: ' + (data.last_update || 'never') + ' · ' + data.schedule_text)),
      h('span', { class: 'status ' + (u.running ? 'running' : 'ok') }, u.running ? 'Updating…' : 'Idle')));
    const start = async (body, label) => {
      try { await post('/api/update', body); toast(label); pollUpdate(true); setTimeout(load, 800); } catch (e) { toast(e.message); }
    };
    updBox.appendChild(h('div', { class: 'row' },
      h('button', { class: 'btn btn-primary', type: 'button', disabled: (!canAdmin || u.running) ? true : null,
        onclick: () => start({}, 'Update started') }, 'Update all sources now'),
      h('button', { class: 'btn', type: 'button', disabled: (!canAdmin || u.running) ? true : null,
        title: 'Also re-process yearly datasets (boundaries, Census, BEA) even if refreshed recently',
        onclick: () => start({ force: true }, 'Full refresh started') }, 'Force full refresh'),
      u.running ? h('button', { class: 'btn', type: 'button', disabled: canAdmin ? null : true, onclick: async () => { await post('/api/update/cancel', {}); toast('Cancelling…'); } }, 'Cancel') : null,
      canAdmin ? null : h('span', { class: 'small muted' }, 'Only the admin account (or this computer) can start updates.')));
    if (u.log && u.log.length) {
      const lb = h('div', { class: 'logbox', style: { marginTop: '12px' } }, u.log.join('\n'));
      updBox.appendChild(lb);
      setTimeout(() => { lb.scrollTop = lb.scrollHeight; }, 0);
    }
    updBox.appendChild(h('p', { class: 'small muted', style: { marginTop: '10px' } },
      'Tip: the app refreshes automatically every week while it is running. To refresh even when the app is closed, run ',
      h('span', { class: 'formula' }, 'python app.py install-schedule'), ' once (Windows Task Scheduler / macOS & Linux cron).'));
    clearTimeout(timer);
    if (u.running) timer = setTimeout(load, 2500);
  }

  function drawList() {
    clear(listBox);
    listBox.appendChild(h('div', { class: 'section-title' }, h('h2', null, 'Sources used'), h('span', { class: 'chip' }, data.sources.length + ' sources')));
    const grid = h('div', { class: 'grid grid-2' });
    listBox.appendChild(grid);
    for (const s of data.sources) {
      const stt = s.status || {};
      const det = stt.details || {};
      const metrics = (s.metrics || []).map((mid) => metric(mid) ? metric(mid).name : mid);
      const card = h('div', { class: 'card src-card' },
        h('h3', null, h('span', null, s.name), h('span', { class: 'status ' + (stt.status || '') }, stt.status || (s.enabled ? 'not run yet' : 'disabled'))),
        h('p', { class: 'secondary small' }, s.description),
        h('div', { class: 'src-meta' },
          h('span', { class: 'k' }, 'Website'), h('a', { href: s.homepage, target: '_blank', rel: 'noopener' }, s.homepage),
          h('span', { class: 'k' }, 'Publishes'), h('span', null, s.frequency),
          h('span', { class: 'k' }, 'Last success'), h('span', null, stt.last_success || '–'),
          h('span', { class: 'k' }, 'Latest data'), h('span', null, det.latest_period || '–'),
          h('span', { class: 'k' }, 'Result'), h('span', null, stt.message || '–'),
          h('span', { class: 'k' }, 'License'), h('span', null, s.license || '')));
      if (det.problems && det.problems.length) {
        card.appendChild(h('details', { class: 'files' }, h('summary', null, det.problems.length + ' warning(s)'),
          h('ul', null, det.problems.map((p) => h('li', null, p)))));
      }
      if (metrics.length) {
        card.appendChild(h('details', { class: 'files' }, h('summary', null, 'Metrics from this source (' + metrics.length + ')'),
          h('div', { class: 'row', style: { marginTop: '6px' } }, metrics.map((n) => h('span', { class: 'chip' }, n)))));
      }
      const files = s.downloads && s.downloads.length ? s.downloads : (s.files || []).map((f) => ({ url: f.url, status: 'not downloaded yet', key: f.key, desc: f.desc }));
      card.appendChild(h('details', { class: 'files' }, h('summary', null, 'Files & URLs (' + files.length + ')'),
        h('ul', null, files.map((f) => h('li', null, h('a', { href: f.url.indexOf('key=') >= 0 ? s.homepage : f.url, target: '_blank', rel: 'noopener' }, f.url.replace(/key=[^&]+/, 'key=…')),
          ' — ', f.status || '', f.bytes ? ' · ' + bytes(f.bytes) : '', f.fetched ? ' · ' + f.fetched : '', f.key ? h('span', { class: 'muted' }, ' [' + f.key + ']') : null)))));
      if (!window.HA_STATIC) card.appendChild(h('div', { class: 'row', style: { marginTop: '10px' } },
        h('button', { class: 'btn btn-small', type: 'button', disabled: (!canAdmin || data.update.running) ? true : null,
          onclick: async () => { try { await post('/api/update', { sources: [s.id] }); toast('Updating ' + s.name); pollUpdate(true); setTimeout(load, 800); } catch (e) { toast(e.message); } } }, 'Update this source'),
        h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: s.enabled, disabled: canAdmin ? null : true,
          onchange: async (e) => { try { await post('/api/settings', { sources: { [s.id]: { enabled: e.target.checked } } }); toast('Saved'); } catch (err) { toast(err.message); } } }), 'Include in updates')));
      grid.appendChild(card);
    }
  }

  function drawOther() {
    clear(otherBox);
    otherBox.appendChild(h('div', { class: 'section-title' }, h('h2', null, 'Other sources reviewed')));
    otherBox.appendChild(h('div', { class: 'card' }, h('ul', { style: { margin: 0, paddingLeft: '18px' } },
      data.other.map((o) => h('li', null, h('a', { href: o.url, target: '_blank', rel: 'noopener' }, o.name), ' — ', h('span', { class: 'secondary' }, o.note))))));
  }

  async function drawSettings() {
    let cfg;
    try { cfg = await api('/api/settings'); } catch (e) { return; }
    clear(settingsBox);
    settingsBox.appendChild(h('div', { class: 'section-title' }, h('h2', null, 'Settings')));
    const a = cfg.affordability || {};
    const sch = cfg.schedule || {};
    const f = {};
    const num = (key, label, val, step = '0.1', help) => {
      f[key] = h('input', { class: 'input', type: 'number', step, value: val === null || val === undefined ? '' : val });
      return h('label', { class: 'field', title: help || null }, label, f[key]);
    };
    const txt = (key, label, val, help, type = 'text') => {
      f[key] = h('input', { class: 'input', type, value: val || '', autocomplete: 'off' });
      return h('label', { class: 'field', title: help || null }, label, f[key], help ? h('span', { class: 'small muted', style: { fontWeight: 400 } }, help) : null);
    };
    f.enabled = h('input', { type: 'checkbox', checked: !!sch.enabled });
    f.weekday = h('select', { class: 'input' }, DAYS.map((d, i) => h('option', { value: i, selected: i === +sch.weekday ? true : null }, d)));
    f.hour = h('select', { class: 'input' }, Array.from({ length: 24 }, (_, i) => h('option', { value: i, selected: i === +sch.hour ? true : null }, String(i).padStart(2, '0') + ':00')));
    f.overrides = h('textarea', { class: 'input', rows: 4, style: { fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '12px' } }, JSON.stringify(cfg.url_overrides || {}, null, 2));
    const save = async () => {
      let overrides;
      try { overrides = JSON.parse(f.overrides.value || '{}'); } catch (e) { toast('URL overrides must be valid JSON'); return; }
      const val = (k) => (f[k].value === '' ? null : +f[k].value);
      const body = {
        contact_email: f.email.value.trim(), census_api_key: f.census.value.trim(), bea_api_key: f.bea.value.trim(),
        bls_api_key: f.bls.value.trim(),
        schedule: { enabled: f.enabled.checked, weekday: +f.weekday.value, hour: +f.hour.value },
        affordability: { down_payment_pct: val('down'), loan_years: val('years'), insurance_rate_pct: val('ins'), pmi_rate_pct: val('pmi'),
          affordable_dti_pct: val('dti'), expense_ratio_pct: val('exp'), rate_override_pct: val('rate'), default_property_tax_pct: val('tax') },
        url_overrides: overrides,
      };
      try {
        const r = await post('/api/settings', body);
        toast(r.rebuilding ? 'Saved – recalculating affordability layers…' : 'Settings saved');
        clearCache();
        if (r.rebuilding) setTimeout(async () => { await refreshMeta(); }, 4000);
      } catch (e) { toast(e.message); }
    };
    settingsBox.appendChild(h('div', { class: 'grid grid-2' },
      h('div', { class: 'card' }, h('h3', null, 'Automatic weekly update'),
        h('label', { class: 'row', style: { margin: '8px 0' } }, f.enabled, 'Refresh data every week while the app is running'),
        h('div', { class: 'settings-grid' }, h('label', { class: 'field' }, 'Day', f.weekday), h('label', { class: 'field' }, 'Time', f.hour)),
        h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Missed runs (computer off) catch up automatically the next time the app starts.')),
      h('div', { class: 'card' }, h('h3', null, 'Contact & API keys (optional)'),
        h('div', { class: 'grid', style: { gap: '10px' } },
          txt('email', 'Contact e-mail (sent in download headers; BLS requires one)', cfg.contact_email, null, 'email'),
          txt('census', 'Census API key', cfg.census_api_key, 'Free at api.census.gov/data/key_signup.html - makes ACS downloads much smaller/faster.'),
          txt('bea', 'BEA API key', cfg.bea_api_key, 'Free at apps.bea.gov/API/signup - only used if the BEA zip download fails.'),
          txt('bls', 'BLS API key', cfg.bls_api_key, 'Free at data.bls.gov/registrationEngine - raises the payroll-jobs API limit (25 → 500 requests/day) and adds 20 years of history.')))));
    settingsBox.appendChild(h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', null, 'Affordability & investing assumptions'),
      h('p', { class: 'small secondary' }, 'Used for Monthly House Payment, Payment % of Income, Income Needed, Buy vs Rent and Cap Rate. Changing these recalculates the map layers.'),
      h('div', { class: 'settings-grid' },
        num('down', 'Down payment (%)', a.down_payment_pct, '1'), num('years', 'Loan term (years)', a.loan_years, '1'),
        num('rate', 'Mortgage rate override (%) – blank = Freddie Mac weekly', a.rate_override_pct, '0.01'),
        num('ins', 'Home insurance (% of value / yr)', a.insurance_rate_pct, '0.05'), num('pmi', 'PMI (% of loan / yr, if <20% down)', a.pmi_rate_pct, '0.05'),
        num('tax', 'Fallback property tax (%)', a.default_property_tax_pct, '0.05'), num('dti', 'Affordable payment share of income (%)', a.affordable_dti_pct, '1'),
        num('exp', 'Rental expense ratio for cap rate (%)', a.expense_ratio_pct, '1'))));
    settingsBox.appendChild(h('div', { class: 'card', style: { marginTop: '14px' } }, h('h3', null, 'Advanced: download URL overrides'),
      h('p', { class: 'small secondary' }, 'If a provider moves a file, paste the new link here as {"key": "url"}. Keys are shown in brackets next to each file above (e.g. redfin_zip, realtor_core_metro, fema_nri_counties).'),
      f.overrides));
    settingsBox.appendChild(h('div', { class: 'row', style: { marginTop: '14px' } },
      h('button', { class: 'btn btn-primary', type: 'button', disabled: canAdmin ? null : true, onclick: save }, 'Save settings'),
      h('span', { class: 'small muted' }, 'Data folder: ' + cfg.data_dir)));
  }

  await load();
  if (!window.HA_STATIC) await drawSettings();
  return { destroy() { clearTimeout(timer); } };
}
