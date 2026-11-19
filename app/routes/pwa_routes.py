"""휴대폰 홈 화면에 '앱'으로 설치할 수 있게 하는 PWA 매니페스트/서비스워커."""

from flask import Blueprint, Response, jsonify

pwa_bp = Blueprint("pwa", __name__)

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="96" fill="#7c5cff"/>
<text x="256" y="330" font-size="260" text-anchor="middle" fill="#fff" font-family="Arial, sans-serif" font-weight="700">$</text>
</svg>"""


@pwa_bp.route("/manifest.webmanifest")
def manifest():
    return jsonify({
        "name": "나만의 미국 소싱 프로그램",
        "short_name": "소싱",
        "start_url": "/us/",
        "display": "standalone",
        "background_color": "#0f1115",
        "theme_color": "#7c5cff",
        "lang": "ko",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
    })


@pwa_bp.route("/icon.svg")
def icon():
    return Response(ICON_SVG, mimetype="image/svg+xml")


@pwa_bp.route("/sw.js")
def service_worker():
    js = """
const CACHE = 'sourcing-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/static/style.css', '/icon.svg'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/static/') || url.pathname === '/icon.svg') {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/"})
