const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST", "PATCH", "DELETE"]);

function securityHeaders(headers) {
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  headers.set(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
  );
  return headers;
}

function jsonResponse(status, payload) {
  const headers = securityHeaders(new Headers({
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  }));
  return new Response(JSON.stringify(payload), { status, headers });
}

async function proxyApi(request, env) {
  if (!ALLOWED_METHODS.has(request.method)) {
    return jsonResponse(405, { status: "METHOD_NOT_ALLOWED", message: "This API method is not allowed." });
  }
  if (!env.DELL_API || typeof env.DELL_API.fetch !== "function") {
    return jsonResponse(503, {
      status: "GATEWAY_NOT_CONFIGURED",
      message: "The private Dell API binding has not been configured yet.",
    });
  }

  const incoming = new URL(request.url);
  const upstream = new URL(`${incoming.pathname}${incoming.search}`, "http://learn-with-stories.internal");
  const headers = new Headers(request.headers);
  for (const name of [
    "host",
    "cookie",
    "cf-access-jwt-assertion",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
    "content-length",
    "connection",
  ]) {
    headers.delete(name);
  }
  const init = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
  }

  try {
    const response = await env.DELL_API.fetch(new Request(upstream, init));
    const responseHeaders = securityHeaders(new Headers(response.headers));
    responseHeaders.delete("set-cookie");
    responseHeaders.set("Cache-Control", "no-store");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch {
    return jsonResponse(502, {
      status: "DELL_API_UNAVAILABLE",
      message: "The Dell service is offline or the Cloudflare Tunnel is disconnected.",
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      return proxyApi(request, env);
    }

    const response = await env.ASSETS.fetch(request);
    const headers = securityHeaders(new Headers(response.headers));
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
