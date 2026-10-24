// 쓰담 중계 서버 — 휴대폰과 컴퓨터가 QR로 나눠 가진 채널(무작위 128비트)로 암호문을 주고받는 우편함.
// 내용은 폰·컴퓨터만 아는 열쇠로 암호화돼 있어서 여기서는 열 수 없다. 받으면 지우고, 14일 지난 것은 R2 수명 규칙이 지운다.
//   GET    /v1/<채널>/<pc|phone>            → 그 상자에 들어 있는 것 목록
//   PUT    /v1/<채널>/<pc|phone>/<이름>     → 넣기 (최대 100MB)
//   GET    /v1/<채널>/<pc|phone>/<이름>     → 꺼내기
//   DELETE /v1/<채널>/<pc|phone>/<이름>     → 지우기
//   DELETE /v1/<채널>                        → 연결 끊기 (채널 전체 지우기)
// 인증: x-relay-token (열쇠에서 만든 값). 처음 쓴 토큰의 해시를 채널에 기억해 두고 다음부터 같은지 확인.
const MAX = 100 * 1024 * 1024;
const MAX_ITEMS = 300;

const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json" } });

async function sha256(t) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/" || url.pathname === "/health") return new Response("sseudam relay ok");
    const m = url.pathname.match(/^\/v1\/([0-9a-f]{32})(?:\/(pc|phone)(?:\/([A-Za-z0-9._-]{1,100}))?)?$/);
    if (!m) return json({ error: "not found" }, 404);
    const [, ch, box, name] = m;
    const token = req.headers.get("x-relay-token") || "";
    if (!/^[0-9a-f]{64}$/.test(token)) return json({ error: "token" }, 401);

    // 채널 주인 확인 (처음 온 토큰을 기억)
    const authKey = `${ch}/.auth`;
    const th = await sha256(token);
    const auth = await env.BOX.get(authKey);
    if (auth) {
      if ((await auth.text()) !== th) return json({ error: "forbidden" }, 403);
    } else {
      await env.BOX.put(authKey, th);
    }

    if (!box) {
      if (req.method !== "DELETE") return json({ error: "method" }, 405);
      let cursor;
      do {
        const l = await env.BOX.list({ prefix: `${ch}/`, cursor });
        if (l.objects.length) await env.BOX.delete(l.objects.map((o) => o.key));
        cursor = l.truncated ? l.cursor : undefined;
      } while (cursor);
      return json({ ok: true });
    }

    const prefix = `${ch}/${box}/`;
    if (!name) {
      if (req.method !== "GET") return json({ error: "method" }, 405);
      const l = await env.BOX.list({ prefix, limit: 1000 });
      return json({ items: l.objects.map((o) => ({ name: o.key.slice(prefix.length), size: o.size, at: o.uploaded })) });
    }

    const key = prefix + name;
    if (req.method === "PUT") {
      const len = Number(req.headers.get("content-length") || 0);
      if (!len || len > MAX) return json({ error: "too large" }, 413);
      const l = await env.BOX.list({ prefix, limit: MAX_ITEMS + 1 });
      if (l.objects.length >= MAX_ITEMS && !l.objects.some((o) => o.key === key)) return json({ error: "full" }, 429);
      await env.BOX.put(key, req.body);
      return json({ ok: true });
    }
    if (req.method === "GET") {
      const o = await env.BOX.get(key);
      if (!o) return json({ error: "not found" }, 404);
      return new Response(o.body, { headers: { "content-type": "application/octet-stream", "content-length": String(o.size) } });
    }
    if (req.method === "DELETE") {
      await env.BOX.delete(key);
      return json({ ok: true });
    }
    return json({ error: "method" }, 405);
  },
};
