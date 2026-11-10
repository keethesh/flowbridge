// Runs inside a logged-in flow.google.com tab (page main world). Evaluated as `(<this>)(args)`.
// Talks to Flow's own Boq batchexecute endpoint, so cookies, XSRF and reCAPTCHA come from the real page.
async (a) => {
  const W = window.WIZ_global_data;
  const RECAPTCHA_KEY = '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV';
  const TOOL = 22; // client id sent in every Flow request context
  const IMAGE_AR = { '16:9': 3, '9:16': 2, '1:1': 1, '4:3': 5, '3:4': 4, '3:2': 7, '2:3': 6, '5:4': 9, '4:5': 8, '21:9': 10, '4:1': 12, '1:4': 11, '8:1': 14, '1:8': 13 };
  const VIDEO_AR = { '16:9': 2, '9:16': 1 };
  const STATUS = { 2: 'pending', 3: 'success', 4: 'failed', 5: 'canceled', 7: 'failed' };
  const uuid = () => crypto.randomUUID().toUpperCase();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pick = (map, k, what) => { if (!(k in map)) throw new Error(`unsupported ${what} ${k}; use one of ${Object.keys(map)}`); return map[k]; };
  const findStr = (x, prefix) => {
    if (typeof x === 'string') return x.startsWith(prefix) ? x : null;
    if (Array.isArray(x)) for (const y of x) { const r = findStr(y, prefix); if (r) return r; }
    return null;
  };

  async function rpc(id, payload) {
    const qs = new URLSearchParams({ rpcids: id, 'source-path': location.pathname, bl: W.cfb2h, 'f.sid': W.FdrFJe, hl: 'en', rt: 'c' });
    const body = new URLSearchParams({ 'f.req': JSON.stringify([[[id, JSON.stringify(payload), null, 'generic']]]), at: W.SNlM0e });
    const r = await fetch('/_/AiSandboxAngularFrontend/data/batchexecute?' + qs, {
      method: 'POST', body,
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'x-same-domain': '1' },
    });
    const text = await r.text();
    if (!r.ok) throw new Error(`${id}: HTTP ${r.status} ${text.slice(0, 300)}`);
    for (const line of text.split('\n')) {
      if (!line.startsWith('[[')) continue;
      for (const e of JSON.parse(line)) {
        if (e[0] !== 'wrb.fr' || e[1] !== id) continue;
        if (e[2] == null) throw new Error(`${id} rejected: ${JSON.stringify(e.slice(3))}`);
        return JSON.parse(e[2]);
      }
    }
    throw new Error(`${id}: no result in response ${text.slice(0, 300)}`);
  }

  async function recaptcha(action) {
    if (!window.grecaptcha?.enterprise) {
      const s = document.createElement('script');
      s.src = `https://www.google.com/recaptcha/enterprise.js?render=${RECAPTCHA_KEY}`;
      document.head.appendChild(s);
    }
    for (let i = 0; !window.grecaptcha?.enterprise?.execute; i++) {
      if (i > 100) throw new Error('reCAPTCHA did not load');
      await sleep(100);
    }
    await new Promise((r) => grecaptcha.enterprise.ready(r));
    return grecaptcha.enterprise.execute(RECAPTCHA_KEY, { action });
  }

  const ctx = (project, token) => [null, TOOL, null, null, null, project, null, null, null, null, [token, 1]];
  const need = (k) => { if (!a[k]) throw new Error(`missing ${k}`); return a[k]; };

  async function media(id) {
    const m = (await rpc('as29s', [id, null, [1]]));
    const code = m[5]?.[8]?.[0];
    const token = findStr(m, 'https://lh3.googleusercontent.com/asb/');
    return {
      media_id: id,
      status: STATUS[code] || 'pending',
      // cookie-authenticated; `=mm,22,15` is what Flow's own player uses (720p, falls back)
      asb_url: token ? token.replace('https://lh3.googleusercontent.com', 'https://flow.google.com') + '=mm,22,15' : null,
    };
  }

  switch (a.op) {
    case 'credits':
      return (await rpc('nzlxg', []))[0];

    case 'models': {
      const cat = (await rpc('HTrJv', []))[0];
      const fmt = (sec) => (sec || []).map(([name, usages, , family]) => ({
        name,
        family: typeof family === 'string' ? family : null,
        keys: usages.map((u) => ({ key: u[0], credits: Object.fromEntries((u[4] || []).filter((t) => t?.[1]?.[0]?.[1] != null).map((t) => [t[0], t[1][0][1]])) })),
      }));
      return { video: fmt(cat[4]), image: fmt(cat[5]) };
    }

    case 'projects':
      return ((await rpc('UpteDb', ['projects/*', 21, null, null, null, null, [1]]))[0] || []).map((p) => ({ id: p[0], title: p[1]?.[0] }));

    case 'create_project':
      return (await rpc('jHPbke', ['projects/*', [null, [a.title || 'Flow API']], [null, TOOL]]))[0];

    case 'image': {
      const project = need('project'), prompt = need('prompt');
      const c = ctx(project, await recaptcha('IMAGE_GENERATION'));
      const ar = pick(IMAGE_AR, a.aspect || '16:9', 'image aspect');
      const items = Array.from({ length: a.count || 1 }, (_, i) => [
        null, null, null, a.seed != null ? a.seed + i : Math.floor(Math.random() * 2 ** 31),
        ar, a.model || 'BELUGA', null, c, [[[prompt]]], null, null, null, uuid(), uuid(), 4,
      ]);
      const d = await rpc('ogiZ0b', [null, items, 1, c, [uuid()]]);
      return d[0].map((m) => ({ media_id: m[0], url: findStr(m, 'https://flow-content.google/image/') }));
    }

    case 'video': {
      const project = need('project'), prompt = need('prompt');
      const c = ctx(project, await recaptcha('VIDEO_GENERATION'));
      const ar = pick(VIDEO_AR, a.aspect || '16:9', 'video aspect');
      const item = [[null, null, [[[prompt]]]], a.model || 'macaron_cookie_t2v_8s_360p', ar, null,
        [null, null, null, null, uuid(), uuid()], null, null, [4]];
      const d = await rpc('YhhmEf', [[item], c, [uuid(), 2]]);
      return { media_id: d[3][0][0], credits_left: d[1] };
    }

    case 'media':
      return media(need('media_id'));

    default:
      throw new Error(`unknown op ${a.op}`);
  }
}
