/**
 * Visitor counter for www.portalaser.com (Cloudflare Pages Function)
 *
 * Route:  /api/visitors
 * Method: GET
 * Reply:  { "today": 12, "week": 87, "total": 1204 }
 *
 * Deduplication rule (as requested):
 *   - the same IP counts as ONE visitor per day     -> today counter
 *   - the same IP counts as ONE visitor per week    -> week counter
 *   - the same IP counts as ONE visitor overall     -> total counter
 *
 * Privacy: IPs are never stored in plain text. Only the first 32 hex chars of
 * SHA-256(IP) are kept as the visitor key.
 *
 * Storage: Cloudflare KV (free plan). Binding name must be `VISITORS_KV`.
 *   Create the namespace in the Cloudflare dashboard and attach it to this
 *   Pages project: Project > Settings > Functions > KV namespace bindings.
 *
 * Note: KV read-modify-write is not atomic; on a very small site the
 * occasional lost increment is negligible. Concurrency-safe versions would
 * need Durable Objects — unnecessary for a fan-site counter.
 */

// Fixed offset for "today"/"week" boundaries (UTC+8, the site owner's timezone)
const TZ_OFFSET_MS = 8 * 60 * 60 * 1000;

function dateKey(d) {
  // local (UTC+8) date as YYYY-MM-DD
  return new Date(d.getTime() + TZ_OFFSET_MS).toISOString().slice(0, 10);
}

function weekKey(d) {
  // Monday of the local (UTC+8) week as YYYY-MM-DD
  const local = new Date(d.getTime() + TZ_OFFSET_MS);
  const day = local.getUTCDay();            // 0 = Sunday
  const diff = day === 0 ? -6 : 1 - day;    // days back to Monday
  local.setUTCDate(local.getUTCDate() + diff);
  return local.toISOString().slice(0, 10);
}

async function hashIp(ip, env) {
  const salt = env.VISITORS_SALT || 'portalaser-default-salt';
  const data = new TextEncoder().encode(ip + '|' + salt);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, 32);
}

async function bump(kv, key) {
  const cur = parseInt((await kv.get(key)) || '0', 10);
  await kv.put(key, String(cur + 1));
  return cur + 1;
}

export async function onRequest(context) {
  const { request, env } = context;
  const kv = env.VISITORS_KV;

  // No KV bound yet -> return zeros so the footer keeps working.
  if (!kv) {
    return Response.json({ today: 0, week: 0, total: 0, enabled: false });
  }

  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const userKey = 'u:' + (await hashIp(ip, env));

  const now = new Date();
  const today = dateKey(now);
  const week = weekKey(now);

  let last = await kv.get(userKey); // YYYY-MM-DD of this IP's last visit, or null

  const isNewVisitor = last === null;
  const isNewDay = last !== today;
  const isNewWeek = last === null || weekKey(new Date(last + 'T00:00:00Z')) !== week;

  if (isNewVisitor || isNewDay || isNewWeek) {
    await kv.put(userKey, today);
    if (isNewVisitor) await bump(kv, 'total');
    if (isNewDay || isNewVisitor) await bump(kv, 'd:' + today);
    if (isNewWeek || isNewVisitor) await bump(kv, 'w:' + week);
  }

  const todayCount = parseInt((await kv.get('d:' + today)) || '0', 10);
  const weekCount = parseInt((await kv.get('w:' + week)) || '0', 10);
  const totalCount = parseInt((await kv.get('total')) || '0', 10);

  return Response.json(
    { today: todayCount, week: weekCount, total: totalCount, enabled: true },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}
