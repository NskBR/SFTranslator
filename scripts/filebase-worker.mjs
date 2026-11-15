const FILEBASE_ENDPOINT = 's3.filebase.io';
const EMPTY_SHA256 =
  'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
const encoder = new TextEncoder();

function toHex(value) {
  return [...new Uint8Array(value)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

async function sha256(value) {
  return crypto.subtle.digest('SHA-256', encoder.encode(value));
}

async function hmac(key, value) {
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    typeof key === 'string' ? encoder.encode(key) : key,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  return crypto.subtle.sign('HMAC', cryptoKey, encoder.encode(value));
}

async function createSignedHeaders(request, originUrl, env) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const region = env.FILEBASE_REGION || 'auto';
  const service = 's3';
  const signedHeaders = 'host;x-amz-content-sha256;x-amz-date';
  const canonicalHeaders =
    `host:${originUrl.host}\n` +
    `x-amz-content-sha256:${EMPTY_SHA256}\n` +
    `x-amz-date:${amzDate}\n`;
  const canonicalRequest = [
    request.method,
    originUrl.pathname,
    '',
    canonicalHeaders,
    signedHeaders,
    EMPTY_SHA256,
  ].join('\n');
  const scope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = [
    'AWS4-HMAC-SHA256',
    amzDate,
    scope,
    toHex(await sha256(canonicalRequest)),
  ].join('\n');

  const dateKey = await hmac(`AWS4${env.FILEBASE_SECRET_ACCESS_KEY}`, dateStamp);
  const regionKey = await hmac(dateKey, region);
  const serviceKey = await hmac(regionKey, service);
  const signingKey = await hmac(serviceKey, 'aws4_request');
  const signature = toHex(await hmac(signingKey, stringToSign));

  const headers = new Headers();
  for (const name of ['range', 'if-match', 'if-none-match', 'if-modified-since']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set('x-amz-content-sha256', EMPTY_SHA256);
  headers.set('x-amz-date', amzDate);
  headers.set(
    'authorization',
    `AWS4-HMAC-SHA256 Credential=${env.FILEBASE_ACCESS_KEY_ID}/${scope}, ` +
      `SignedHeaders=${signedHeaders}, Signature=${signature}`,
  );
  return headers;
}

const publicPath = /^\/sftranslator\/desktop\/(?:latest\.json|releases\/\d+\.\d+\.\d+\/(?:SFTranslator-Windows-x64-setup\.exe|patch-notes\.txt))$/;

export default {
  async fetch(request, env) {
    const { pathname, search } = new URL(request.url);
    const noStore = { 'cache-control': 'no-store' };
    if (!['GET', 'HEAD'].includes(request.method)) {
      return new Response(null, { status: 405, headers: { ...noStore, allow: 'GET, HEAD' } });
    }
    if (pathname === '/healthz' && !search) {
      return new Response(null, { status: 204, headers: noStore });
    }
    if (search || !publicPath.test(pathname)) {
      return new Response(null, { status: 404, headers: noStore });
    }
    if (!env.FILEBASE_ACCESS_KEY_ID || !env.FILEBASE_SECRET_ACCESS_KEY ||
        !/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(env.FILEBASE_BUCKET)) {
      return new Response(null, { status: 503, headers: noStore });
    }
    const originPath = pathname.replace('/sftranslator/desktop/', '/sftranslator-updates/');
    const originUrl = new URL('https://' + env.FILEBASE_BUCKET + '.' + FILEBASE_ENDPOINT + originPath);
    try {
      const headers = await createSignedHeaders(request, originUrl, env);
      const origin = await fetch(originUrl, { method: request.method, headers, redirect: 'manual', cache: 'no-store' });
      const status = origin.status;
      if (![200, 206, 304, 404, 412, 416].includes(status)) {
        await origin.body?.cancel();
        console.error(JSON.stringify({ event: 'filebase_origin_error', status }));
        return new Response(null, { status: 502, headers: noStore });
      }
      const outgoing = new Headers(noStore);
      for (const name of ['content-type', 'content-range', 'accept-ranges', 'etag', 'last-modified']) {
        const value = origin.headers.get(name);
        if (value) outgoing.set(name, value);
      }
      const serveBody = request.method === 'GET' && [200, 206].includes(status);
      if (status === 200 || status === 206) {
        const length = origin.headers.get('content-length');
        if (length) outgoing.set('content-length', length);
      }
      if (!serveBody) await origin.body?.cancel();
      return new Response(serveBody ? origin.body : null, { status, headers: outgoing });
    } catch {
      console.error(JSON.stringify({ event: 'filebase_fetch_failed' }));
      return new Response(null, { status: 502, headers: noStore });
    }
  },
};
