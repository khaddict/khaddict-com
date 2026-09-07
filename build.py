#!/usr/bin/env python3
"""Renders the shared-chrome Jinja2 templates into the static HTML files that
Helm and the vps-fallback host serve. templates/ is the only source of truth;
generated output is never committed. CI (publish-chart.yaml) runs this with no
arguments right before `helm package`. For local Helm testing, run it the same
way to populate the real paths on disk. For a quick preview without touching
those paths, use --out-dir (e.g. --out-dir _preview, already gitignored).
"""
import argparse
import base64
import json
import pathlib
import re
import subprocess
from datetime import datetime, timezone
from email.utils import format_datetime

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
I18N_DIR = TEMPLATES / "data" / "i18n"
ASSETS_DIR = TEMPLATES / "data" / "assets"

BRAND_ICON_URL = None
WALL_SCENE_URL = None

PROD_API_BASE_URL = "https://api.khaddict.com"


def fallback_icon_data_uri():
    data = (ASSETS_DIR / "vps-fallback-icon.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

LOCALES = ("en", "fr")

def build_site_urls(domain, scheme):
    return {
        "en": {
            "brand": "/",
            "home": f"{scheme}://{domain}",
            "blog": f"{scheme}://blog.{domain}",
            "projects": f"{scheme}://projects.{domain}",
            "media": f"{scheme}://media.{domain}",
            "dashboard": f"{scheme}://dashboard.{domain}",
            "api": f"{scheme}://api.{domain}",
            "diagram": f"{scheme}://diagram.{domain}",
        },
        "fr": {
            "brand": "/fr/",
            "home": f"{scheme}://{domain}/fr/",
            "blog": f"{scheme}://blog.{domain}/fr/",
            "projects": f"{scheme}://projects.{domain}/fr/",
            "media": f"{scheme}://media.{domain}/fr/",
            "dashboard": f"{scheme}://dashboard.{domain}",
            "api": f"{scheme}://api.{domain}/fr/",
            "diagram": f"{scheme}://diagram.{domain}/fr/",
        },
    }

def build_page_meta(domain, scheme, subdomain, en_description, fr_description):
    host = f"{subdomain}.{domain}" if subdomain else domain
    return {
        "en": {
            "description": en_description,
            "og_url": f"{scheme}://{host}/",
            "og_locale": "en_US",
            "og_locale_alternate": "fr_FR",
            "canonical_url": f"{scheme}://{host}/",
        },
        "fr": {
            "description": fr_description,
            "og_url": f"{scheme}://{host}/fr/",
            "og_locale": "fr_FR",
            "og_locale_alternate": "en_US",
            "canonical_url": f"{scheme}://{host}/fr/",
        },
    }


def build_www_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "",
        "Personal space dedicated to homelab, self-hosted infrastructure and code.",
        "Espace personnel dédié au homelab, à l’infrastructure self-hosted et au code.",
    )


WWW_META = None

TAG_COLORS_LIGHT = {
    "homelab": "#7C5CBF",
    "printing3d": "#A85A26",
    "tooling": "#2E6DAE",
    "systems": "#1A7557",
    "networking": "#B03E71",
    "cloud": "#1C7F97",
    "dev": "#A6790F",
}
TAG_COLORS_DARK = {
    "homelab": "#B39DDB",
    "printing3d": "#F5B78E",
    "tooling": "#90CAF9",
    "systems": "#A5D6C1",
    "networking": "#F0A8C4",
    "cloud": "#8ED2E0",
    "dev": "#F0C674",
}


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return ", ".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def _tag_declarations(colors, alpha, inline):
    """One `--tag-<name>[-bg]` declaration pair per tag; `inline` puts both on one line."""
    parts = []
    for tag, hex_color in colors.items():
        bg = f"rgba({_hex_to_rgb(hex_color)}, {alpha})"
        if inline:
            parts.append(f"--tag-{tag}: {hex_color}; --tag-{tag}-bg: {bg};")
        else:
            parts.append(f"--tag-{tag}: {hex_color};")
            parts.append(f"--tag-{tag}-bg: {bg};")
    return parts


BLOG_EXTRA_TOKENS = {
    "extra_tokens_base": "\n      ".join(_tag_declarations(TAG_COLORS_LIGHT, ".12", inline=False)),
    "extra_tokens_dark_media": "\n        ".join(_tag_declarations(TAG_COLORS_DARK, ".15", inline=False)),
    "extra_tokens_light_attr": "\n      ".join(_tag_declarations(TAG_COLORS_LIGHT, ".12", inline=True)),
    "extra_tokens_dark_attr": "\n      ".join(_tag_declarations(TAG_COLORS_DARK, ".15", inline=True)),
}

NO_EXTRA_TOKENS = {
    "extra_tokens_base": "",
    "extra_tokens_dark_media": "",
    "extra_tokens_light_attr": "",
    "extra_tokens_dark_attr": "",
}

def build_blog_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "blog",
        "Blog on homelab, self-hosted infrastructure, tooling and more. Articles in progress.",
        "Blog sur le homelab, l’infrastructure self-hosted, les outils et plus. Articles en cours de rédaction.",
    )


def build_projects_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "projects",
        "Projects I build and run: voidnode, khaddict-com, homelab, easypki.",
        "Projets que je construis et fais tourner : voidnode, khaddict-com, homelab, easypki.",
    )


def build_media_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "media",
        "Personal media gallery hosting icons, wallpapers, homelab videos and assets.",
        "Galerie personnelle hébergeant icônes, fonds d’écran, vidéos et assets du homelab.",
    )


def build_api_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "api",
        "Public gateway API that drives IoT devices around the homelab, starting with the BUSY Bar.",
        "Public gateway API that drives IoT devices around the homelab, starting with the BUSY Bar.",
    )


def build_diagram_meta(domain, scheme):
    return build_page_meta(
        domain, scheme, "diagram",
        "Interactive network map of the khaddict homelab: VLANs, devices, and how they connect.",
        "Interactive network map of the khaddict homelab: VLANs, devices, and how they connect.",
    )


BLOG_META = None
PROJECTS_META = None
MEDIA_META = None
API_META = None
DIAGRAM_META = None

NOT_FOUND_DESCRIPTION = "This page doesn't exist."


def build_rss_hrefs(domain, scheme):
    return {
        "en": f"{scheme}://blog.{domain}/feed.xml",
        "fr": f"{scheme}://blog.{domain}/fr/feed.xml",
    }


def build_sitemap_entries(posts):
    base = "https://khaddict.com"
    blog = "https://blog.khaddict.com"
    projects = "https://projects.khaddict.com"
    media = "https://media.khaddict.com"
    diagram = "https://diagram.khaddict.com"
    api = "https://api.khaddict.com"

    entries = []

    def add(en_url, fr_url):
        entries.append({"loc": en_url, "en": en_url, "fr": fr_url, "x_default": en_url})
        entries.append({"loc": fr_url, "en": en_url, "fr": fr_url, "x_default": en_url})

    add(f"{base}/", f"{base}/fr/")
    add(f"{blog}/", f"{blog}/fr/")
    for slug in sorted(posts, key=lambda s: posts[s]["date"], reverse=True):
        add(f"{blog}/posts/{slug}/", f"{blog}/fr/posts/{slug}/")
    add(f"{projects}/", f"{projects}/fr/")
    add(f"{media}/", f"{media}/fr/")
    add(f"{diagram}/", f"{diagram}/fr/")
    add(f"{api}/", f"{api}/fr/")

    return entries


READING_WPM = 225
HTML_TAG_RE = re.compile(r"<[^>]+>")


def reading_time_minutes(html):
    text = HTML_TAG_RE.sub(" ", html)
    word_count = len(text.split())
    return max(1, round(word_count / READING_WPM))


RSS_HREFS = None

GALLERY_DIR = ROOT / "media-build" / "media" / "gallery"


def gallery_filenames_by_recency():
    """Gallery filenames, most recently added first. Uses git history (not
    filesystem mtime, which a fresh CI checkout would reset for every file)."""
    filenames = sorted(p.name for p in GALLERY_DIR.iterdir() if p.is_file())
    try:
        log = subprocess.run(
            ["git", "log", "--diff-filter=A", "--name-only", "--format=", "--", "media-build/media/gallery/"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        added_order = [pathlib.Path(line).name for line in log.splitlines() if line.strip()]
        uncommitted = [f for f in filenames if f not in added_order]
        seen = set()
        committed = [f for f in added_order if f in filenames and not (f in seen or seen.add(f))]
        return uncommitted + committed
    except (subprocess.CalledProcessError, FileNotFoundError):
        return filenames


def hreflang_hrefs(site_key):
    """hreflang link hrefs for a site's root; same values as lang_switch_hrefs(), keyed differently."""
    en = SITE_URLS["en"][site_key] + "/"
    return {
        "hreflang_en_href": en,
        "hreflang_fr_href": SITE_URLS["fr"][site_key],
        "hreflang_x_default_href": en,
    }


def build_feed_items(posts, locale, domain, scheme):
    items = []
    for slug, post in sorted(posts.items(), key=lambda kv: kv[1]["date"], reverse=True):
        pub_date = datetime.strptime(post["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        link = f"{scheme}://blog.{domain}/{'fr/' if locale == 'fr' else ''}posts/{slug}/"
        items.append({
            "title": post["title"][locale],
            "link": link,
            "pub_date": format_datetime(pub_date),
            "description": post["excerpt"][locale],
        })
    return items


def nav_hrefs(urls):
    return {
        "nav_home_href": urls["home"],
        "nav_blog_href": urls["blog"],
        "nav_projects_href": urls["projects"],
        "nav_media_href": urls["media"],
        "nav_dashboard_href": urls["dashboard"],
        "nav_api_href": urls["api"],
        "nav_diagram_href": urls["diagram"],
    }


def lang_switch_hrefs(site_key):
    """Locale-switcher hrefs: always the subdomain root, not the current page (matches the pre-template convention)."""
    return {
        "lang_switch_fr_href": SITE_URLS["fr"][site_key],
        "lang_switch_en_href": SITE_URLS["en"][site_key] + "/",
    }


def build_search_posts(site_urls, posts):
    return [
        {
            "slug": slug,
            "title": post["title"],
            "excerpt": post["excerpt"],
            "url": {
                "en": f"{site_urls['en']['blog']}/posts/{slug}/",
                "fr": f"{site_urls['fr']['blog']}posts/{slug}/",
            },
        }
        for slug, post in sorted(posts.items(), key=lambda kv: kv[1]["date"], reverse=True)
    ]


def build_search_media(site_urls):
    return [
        {"name": filename, "url": f"{site_urls['en']['media']}/gallery/{filename}"}
        for filename in gallery_filenames_by_recency()
    ]


def load_i18n(name):
    with open(I18N_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def merged_i18n(*sources):
    return {
        locale: {k: v for src in sources for k, v in src[locale].items()}
        for locale in LOCALES
    }


def render(env, template_name, out_path, **context):
    html = env.get_template(template_name).render(**context)
    if not html.endswith("\n"):
        html += "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path}")


PAGE_CHOICES = ["www", "vps-fallback", "blog", "projects", "media", "api", "diagram", "404", "posts", "feed", "sitemap"]


def main():
    parser = argparse.ArgumentParser(description="Render the site's Jinja2 templates.")
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=ROOT,
        help="Write generated pages under this directory instead of the repo root "
        "(for local preview only: point it somewhere outside the repo, or under "
        "the gitignored _preview/, so nothing gets committed by mistake).",
    )
    parser.add_argument(
        "--only",
        choices=PAGE_CHOICES,
        help="Render only this page instead of the whole site, e.g. --only vps-fallback "
        "for the 503 page you deploy by hand.",
    )
    parser.add_argument(
        "--domain",
        default="khaddict.com",
        help="Base domain for every self-referential link this build produces (nav, brand "
        "link, lang switcher, canonical/OG/hreflang, icons, RSS), e.g. --domain "
        "website.khaddict.lab for a local/preprod build that stays fully on that environment "
        "instead of the real site. vps-fallback ignores this and always points at the real "
        "khaddict.com, since representing the real public site during an outage is its job.",
    )
    parser.add_argument(
        "--scheme",
        default="https",
        choices=["http", "https"],
        help="Scheme for --domain's links, e.g. --scheme http for a TLS-less local stack.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]+)?", args.domain):
        parser.error(f"--domain {args.domain!r} contains characters that aren't valid in a hostname")
    out_root = args.out_dir.resolve()
    only = args.only

    global SITE_URLS, BRAND_ICON_URL, WALL_SCENE_URL, WWW_META, BLOG_META, PROJECTS_META, MEDIA_META, API_META, DIAGRAM_META, RSS_HREFS
    SITE_URLS = build_site_urls(args.domain, args.scheme)
    BRAND_ICON_URL = f"{args.scheme}://media.{args.domain}/icons/khazix-pc-flat.png"
    WALL_SCENE_URL = f"{args.scheme}://media.{args.domain}/gallery/wall-scene.png"
    WWW_META = build_www_meta(args.domain, args.scheme)
    BLOG_META = build_blog_meta(args.domain, args.scheme)
    PROJECTS_META = build_projects_meta(args.domain, args.scheme)
    MEDIA_META = build_media_meta(args.domain, args.scheme)
    API_META = build_api_meta(args.domain, args.scheme)
    DIAGRAM_META = build_diagram_meta(args.domain, args.scheme)
    RSS_HREFS = build_rss_hrefs(args.domain, args.scheme)

    prod_site_urls = build_site_urls("khaddict.com", "https")

    cookie_domain = f".{args.domain}"
    cookie_secure_attr = "; Secure" if args.scheme == "https" else ""

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    def safe_tojson(value):
        return (
            json.dumps(value)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )

    env.filters["tojson"] = safe_tojson

    common = load_i18n("common")
    with open(TEMPLATES / "data" / "posts.yaml", encoding="utf-8") as f:
        posts = yaml.safe_load(f)
    for post in posts.values():
        post["reading_time"] = {locale: reading_time_minutes(post["body"][locale]) for locale in LOCALES}

    search_posts = build_search_posts(SITE_URLS, posts)
    search_media = build_search_media(SITE_URLS)

    if only in (None, "www"):
        www_yaml = load_i18n("www")
        www_i18n_all = merged_i18n(common, www_yaml)
        for locale, out_rel in (("en", "files/www/index.html"), ("fr", "files/www/fr/index.html")):
            render(
                env,
                "pages/www.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=www_i18n_all[locale],
                i18n_all=www_i18n_all,
                search_posts=search_posts,
                search_media=search_media,
                brand_href=SITE_URLS[locale]["brand"],
                **nav_hrefs(SITE_URLS[locale]),
                api_base_url=PROD_API_BASE_URL,
                brand_icon_src=BRAND_ICON_URL,
                wall_scene_src=WALL_SCENE_URL,
                meta_description=WWW_META[locale]["description"],
                og_url=WWW_META[locale]["og_url"],
                og_locale=WWW_META[locale]["og_locale"],
                og_locale_alternate=WWW_META[locale]["og_locale_alternate"],
                canonical_url=WWW_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("home"),
                **hreflang_hrefs("home"),
            )

    if only in (None, "vps-fallback"):
        vps_yaml = load_i18n("vps_fallback")
        vps_i18n_all = merged_i18n(common, vps_yaml)
        render(
            env,
            "pages/vps_fallback.html.j2",
            out_root / "vps-fallback/index.html",
            lang="en",
            lang_mode="cookie",
            lang_current="FR",
            i18n=vps_i18n_all["en"],
            i18n_all=vps_i18n_all,
            search_posts=build_search_posts(prod_site_urls, posts),
            search_media=build_search_media(prod_site_urls),
            api_base_url=PROD_API_BASE_URL,
            brand_href=prod_site_urls["en"]["brand"],
            **nav_hrefs(prod_site_urls["en"]),
            brand_icon_src=fallback_icon_data_uri(),
            meta_description=vps_i18n_all["en"]["error.message"],
            cookie_domain=".khaddict.com",
            cookie_secure_attr="; Secure",
            **NO_EXTRA_TOKENS,
        )

    if only in (None, "blog"):
        blog_yaml = load_i18n("blog")
        blog_i18n_all = merged_i18n(common, blog_yaml)
        for locale, out_rel in (("en", "files/blog/index.html"), ("fr", "files/blog/fr/index.html")):
            render(
                env,
                "pages/blog.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=blog_i18n_all[locale],
                i18n_all=blog_i18n_all,
                posts=posts,
                search_posts=search_posts,
                search_media=search_media,
                api_base_url=PROD_API_BASE_URL,
                brand_href=SITE_URLS[locale]["home"],
                **nav_hrefs(SITE_URLS[locale]),
                brand_icon_src=BRAND_ICON_URL,
                meta_description=BLOG_META[locale]["description"],
                og_url=BLOG_META[locale]["og_url"],
                og_locale=BLOG_META[locale]["og_locale"],
                og_locale_alternate=BLOG_META[locale]["og_locale_alternate"],
                canonical_url=BLOG_META[locale]["canonical_url"],
                rss_href=RSS_HREFS[locale],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **BLOG_EXTRA_TOKENS,
                **lang_switch_hrefs("blog"),
                **hreflang_hrefs("blog"),
            )

    if only in (None, "projects"):
        projects_yaml = load_i18n("projects")
        projects_i18n_all = merged_i18n(common, projects_yaml)
        for locale, out_rel in (("en", "files/projects/index.html"), ("fr", "files/projects/fr/index.html")):
            render(
                env,
                "pages/projects.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=projects_i18n_all[locale],
                i18n_all=projects_i18n_all,
                search_posts=search_posts,
                search_media=search_media,
                api_base_url=PROD_API_BASE_URL,
                brand_href=SITE_URLS[locale]["home"],
                **nav_hrefs(SITE_URLS[locale]),
                brand_icon_src=BRAND_ICON_URL,
                meta_description=PROJECTS_META[locale]["description"],
                og_url=PROJECTS_META[locale]["og_url"],
                og_locale=PROJECTS_META[locale]["og_locale"],
                og_locale_alternate=PROJECTS_META[locale]["og_locale_alternate"],
                canonical_url=PROJECTS_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("projects"),
                **hreflang_hrefs("projects"),
            )

    if only in (None, "media"):
        media_yaml = load_i18n("media")
        media_i18n_all = merged_i18n(common, media_yaml)
        for locale, out_rel in (("en", "files/media/index.html"), ("fr", "files/media/fr/index.html")):
            render(
                env,
                "pages/media.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=media_i18n_all[locale],
                i18n_all=media_i18n_all,
                search_posts=search_posts,
                search_media=search_media,
                api_base_url=PROD_API_BASE_URL,
                brand_href=SITE_URLS[locale]["home"],
                **nav_hrefs(SITE_URLS[locale]),
                brand_icon_src=BRAND_ICON_URL,
                meta_description=MEDIA_META[locale]["description"],
                og_url=MEDIA_META[locale]["og_url"],
                og_locale=MEDIA_META[locale]["og_locale"],
                og_locale_alternate=MEDIA_META[locale]["og_locale_alternate"],
                canonical_url=MEDIA_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("media"),
                **hreflang_hrefs("media"),
            )

    if only in (None, "api"):
        api_yaml = load_i18n("api")
        api_i18n_all = merged_i18n(common, api_yaml)
        for locale, out_rel in (("en", "files/api/index.html"), ("fr", "files/api/fr/index.html")):
            render(
                env,
                "pages/api.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=api_i18n_all[locale],
                i18n_all=api_i18n_all,
                search_posts=search_posts,
                search_media=search_media,
                brand_href=SITE_URLS[locale]["home"],
                **nav_hrefs(SITE_URLS[locale]),
                brand_icon_src=BRAND_ICON_URL,
                meta_description=API_META[locale]["description"],
                og_url=API_META[locale]["og_url"],
                og_locale=API_META[locale]["og_locale"],
                og_locale_alternate=API_META[locale]["og_locale_alternate"],
                canonical_url=API_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                api_base_url=PROD_API_BASE_URL,
                french_unavailable=True,
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("api"),
                **hreflang_hrefs("api"),
            )

    if only in (None, "diagram"):
        diagram_yaml = load_i18n("diagram")
        diagram_i18n_all = merged_i18n(common, diagram_yaml)
        for locale, out_rel in (("en", "files/diagram/index.html"), ("fr", "files/diagram/fr/index.html")):
            render(
                env,
                "pages/diagram.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=diagram_i18n_all[locale],
                i18n_all=diagram_i18n_all,
                search_posts=search_posts,
                search_media=search_media,
                brand_href=SITE_URLS[locale]["home"],
                **nav_hrefs(SITE_URLS[locale]),
                brand_icon_src=BRAND_ICON_URL,
                meta_description=DIAGRAM_META[locale]["description"],
                og_url=DIAGRAM_META[locale]["og_url"],
                og_locale=DIAGRAM_META[locale]["og_locale"],
                og_locale_alternate=DIAGRAM_META[locale]["og_locale_alternate"],
                canonical_url=DIAGRAM_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                api_base_url=PROD_API_BASE_URL,
                french_unavailable=True,
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("diagram"),
                **hreflang_hrefs("diagram"),
            )

    if only in (None, "404"):
        not_found_yaml = load_i18n("404")
        not_found_i18n_all = merged_i18n(common, not_found_yaml)
        render(
            env,
            "pages/404.html.j2",
            out_root / "files/shared/404.html",
            lang="en",
            lang_mode="url",
            lang_current="EN",
            i18n=not_found_i18n_all["en"],
            i18n_all=not_found_i18n_all,
            search_posts=search_posts,
                search_media=search_media,
            api_base_url=PROD_API_BASE_URL,
            brand_href="/",
            **nav_hrefs(SITE_URLS["en"]),
            brand_icon_src=BRAND_ICON_URL,
            meta_description=NOT_FOUND_DESCRIPTION,
            lang_switch_fr_href="/fr/",
            lang_switch_en_href="/",
            cookie_domain=cookie_domain,
            cookie_secure_attr=cookie_secure_attr,
            **NO_EXTRA_TOKENS,
        )

    if only in (None, "posts"):
        post_yaml = load_i18n("post")
        for slug, post in posts.items():
            related_candidates = [kv for kv in posts.items() if kv[0] != slug]
            related_candidates.sort(key=lambda kv: kv[1]["date"], reverse=True)
            related_slugs = [s for s, _ in related_candidates][:3]

            post_extra = {
                locale: {
                    "title.post": f"{post['title'][locale]} | khaddict blog",
                    "post.title": post["title"][locale],
                    "post.body": post["body"][locale].replace("{MEDIA}", SITE_URLS["en"]["media"]),
                    **post_yaml[locale],
                }
                for locale in LOCALES
            }
            post_i18n_all = merged_i18n(common, post_extra)

            for locale, out_rel in (
                ("en", f"files/blog/posts/{slug}/index.html"),
                ("fr", f"files/blog/fr/posts/{slug}/index.html"),
            ):
                render(
                    env,
                    "pages/post.html.j2",
                    out_root / out_rel,
                    lang=locale,
                    lang_mode="url",
                    lang_current=locale.upper(),
                    i18n=post_i18n_all[locale],
                    i18n_all=post_i18n_all,
                    slug=slug,
                    post=post,
                    posts=posts,
                    search_posts=search_posts,
                    search_media=search_media,
                    related_slugs=related_slugs,
                    brand_href=SITE_URLS[locale]["home"],
                    **nav_hrefs(SITE_URLS[locale]),
                    brand_icon_src=BRAND_ICON_URL,
                    meta_description=post["excerpt"][locale],
                    media_base=SITE_URLS["en"]["media"],
                    og_image=f"{SITE_URLS['en']['media']}/gallery/{post['cover']}",
                    og_url=f"{args.scheme}://blog.{args.domain}/{'fr/' if locale == 'fr' else ''}posts/{slug}/",
                    og_locale="fr_FR" if locale == "fr" else "en_US",
                    og_locale_alternate="en_US" if locale == "fr" else "fr_FR",
                    canonical_url=f"{args.scheme}://blog.{args.domain}/{'fr/' if locale == 'fr' else ''}posts/{slug}/",
                    hreflang_en_href=f"{args.scheme}://blog.{args.domain}/posts/{slug}/",
                    hreflang_fr_href=f"{args.scheme}://blog.{args.domain}/fr/posts/{slug}/",
                    hreflang_x_default_href=f"{args.scheme}://blog.{args.domain}/posts/{slug}/",
                    lang_switch_fr_href=f"/fr/posts/{slug}/",
                    lang_switch_en_href=f"/posts/{slug}/",
                    rss_href=RSS_HREFS[locale],
                    api_base_url=PROD_API_BASE_URL,
                    cookie_domain=cookie_domain,
                    cookie_secure_attr=cookie_secure_attr,
                    **BLOG_EXTRA_TOKENS,
                )

    if only in (None, "feed"):
        for locale, out_rel in (("en", "files/blog/feed.xml"), ("fr", "files/blog/fr/feed.xml")):
            render(
                env,
                "pages/feed.xml.j2",
                out_root / out_rel,
                channel_link=BLOG_META[locale]["canonical_url"],
                rss_href=RSS_HREFS[locale],
                channel_description=BLOG_META[locale]["description"],
                language="fr-fr" if locale == "fr" else "en-us",
                items=build_feed_items(posts, locale, args.domain, args.scheme),
            )

    if only in (None, "sitemap"):
        render(
            env,
            "pages/sitemap.xml.j2",
            out_root / "files/www/sitemap.xml",
            entries=build_sitemap_entries(posts),
        )


if __name__ == "__main__":
    main()
