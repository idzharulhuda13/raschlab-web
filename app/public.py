from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from app.ui import initials_for

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["initials_for"] = initials_for

ROBOTS_TXT_CONTENT = """User-agent: *
Allow: /
Sitemap: https://raschlab.idzharulhuda.com/sitemap.xml
"""

SITEMAP_XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://raschlab.idzharulhuda.com/</loc>
    <lastmod>2026-10-08</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  <url>
    <loc>https://raschlab.idzharulhuda.com/about</loc>
    <lastmod>2026-10-08</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  <url>
    <loc>https://raschlab.idzharulhuda.com/pricing</loc>
    <lastmod>2026-10-08</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  <url>
    <loc>https://raschlab.idzharulhuda.com/changelog</loc>
    <lastmod>2026-10-08</lastmod>
    <changefreq>monthly</changefreq>
  </url>
</urlset>
"""


@router.get("/about", response_class=HTMLResponse)
def get_about(request: Request):
    return templates.TemplateResponse(request=request, name="about.html", context={})


@router.get("/pricing", response_class=HTMLResponse)
def get_pricing(request: Request):
    return templates.TemplateResponse(request=request, name="pricing.html", context={})


@router.get("/changelog", response_class=HTMLResponse)
def get_changelog(request: Request):
    return templates.TemplateResponse(request=request, name="changelog.html", context={})


@router.get("/robots.txt", response_class=PlainTextResponse)
def get_robots():
    return PlainTextResponse(content=ROBOTS_TXT_CONTENT, media_type="text/plain")


@router.get("/sitemap.xml")
def get_sitemap():
    return Response(content=SITEMAP_XML_CONTENT, media_type="application/xml")
