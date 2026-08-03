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
import pathlib
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
I18N_DIR = TEMPLATES / "data" / "i18n"
ASSETS_DIR = TEMPLATES / "data" / "assets"

# The live site links the brand icon (and og:image/twitter:image/favicon
# everywhere else) straight to media.<domain>, built from --domain/--scheme
# in main() same as SITE_URLS. The vps-fallback page is shown precisely when
# the homelab (and therefore media.khaddict.com) is unreachable, so it keeps
# its own copy inlined as a base64 data URI instead, sized down from
# media-build/media/icons/khazix-pc-flat.png - unaffected by --domain.
BRAND_ICON_URL = None


def fallback_icon_data_uri():
    data = (ASSETS_DIR / "vps-fallback-icon.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

LOCALES = ("en", "fr")

# Per-locale site URLs, used for the header nav / brand link / lang switcher -
# the cross-subdomain links that are genuinely different hosts even in prod.
# Built from --domain/--scheme (main()) rather than hardcoded so a non-prod
# build (--domain website.khaddict.lab --scheme http) keeps every self-
# referential link (nav, canonical/OG/hreflang, icons, RSS) on that same
# environment instead of pointing out at the real site. The one deliberate
# exception is vps-fallback, which always represents the real public site
# (that's its whole job during an outage) and ignores --domain entirely.
def build_site_urls(domain, scheme):
    return {
        "en": {
            "brand": "/",
            "home": f"{scheme}://{domain}",
            "blog": f"{scheme}://blog.{domain}",
            "projects": f"{scheme}://projects.{domain}",
            "media": f"{scheme}://media.{domain}",
            "dashboard": f"{scheme}://dashboard.{domain}",
        },
        "fr": {
            "brand": "/fr/",
            "home": f"{scheme}://{domain}/fr/",
            "blog": f"{scheme}://blog.{domain}/fr/",
            "projects": f"{scheme}://projects.{domain}/fr/",
            "media": f"{scheme}://media.{domain}/fr/",
            "dashboard": f"{scheme}://dashboard.{domain}",
        },
    }

def build_www_meta(domain, scheme):
    return {
        "en": {
            "description": "Personal space dedicated to homelab, self-hosted infrastructure and code.",
            "og_url": f"{scheme}://{domain}",
            "og_locale": "en_US",
            "og_locale_alternate": "fr_FR",
            "canonical_url": f"{scheme}://{domain}/",
        },
        "fr": {
            "description": "Espace personnel dédié au homelab, à l’infrastructure self-hosted et au code.",
            "og_url": f"{scheme}://{domain}/fr/",
            "og_locale": "fr_FR",
            "og_locale_alternate": "en_US",
            "canonical_url": f"{scheme}://{domain}/fr/",
        },
    }


WWW_META = None

# --danger-dim only exists on the home page (used by .deploy-panel::after);
# vps-fallback has no equivalent element so it gets no extra token at all.
WWW_EXTRA_TOKENS = {
    "extra_tokens_base": "--danger-dim:         rgba(239, 68, 68, .10);",
    "extra_tokens_dark_media": "--danger-dim:          rgba(239, 68, 68, .16);",
    "extra_tokens_light_attr": "--danger-dim: rgba(239, 68, 68, .10);",
    "extra_tokens_dark_attr": "--danger-dim: rgba(239, 68, 68, .16);",
}

# projects/index.html carries the same --danger-dim token as the home page
# (copy-pasted from it when projects was hand-authored) even though nothing on
# the projects page currently references var(--danger-dim). Kept for byte
# parity with the file as it existed before this refactor.
PROJECTS_EXTRA_TOKENS = WWW_EXTRA_TOKENS

# --tag-* tokens back the per-tag colors on blog listing cards, post tag
# chips, and the blog's tag-filter chips. Shared by blog.html.j2 and
# post.html.j2 (both render article/post tag chips).
BLOG_EXTRA_TOKENS = {
    "extra_tokens_base": "\n      ".join([
        "--tag-homelab:        #7C5CBF;",
        "--tag-homelab-bg:     rgba(124, 92, 191, .12);",
        "--tag-printing3d:    #A85A26;",
        "--tag-printing3d-bg: rgba(168, 90, 38, .12);",
        "--tag-tooling:        #2E6DAE;",
        "--tag-tooling-bg:     rgba(46, 109, 174, .12);",
        "--tag-systems:        #1A7557;",
        "--tag-systems-bg:     rgba(26, 117, 87, .12);",
        "--tag-networking:         #B03E71;",
        "--tag-networking-bg:      rgba(176, 62, 113, .12);",
        "--tag-cloud:          #1C7F97;",
        "--tag-cloud-bg:       rgba(28, 127, 151, .12);",
    ]),
    "extra_tokens_dark_media": "\n        ".join([
        "--tag-homelab:        #B39DDB;",
        "--tag-homelab-bg:     rgba(179, 157, 219, .15);",
        "--tag-printing3d:    #F5B78E;",
        "--tag-printing3d-bg: rgba(245, 183, 142, .15);",
        "--tag-tooling:        #90CAF9;",
        "--tag-tooling-bg:     rgba(144, 202, 249, .15);",
        "--tag-systems:        #A5D6C1;",
        "--tag-systems-bg:     rgba(165, 214, 193, .15);",
        "--tag-networking:         #F0A8C4;",
        "--tag-networking-bg:      rgba(240, 168, 196, .15);",
        "--tag-cloud:          #8ED2E0;",
        "--tag-cloud-bg:       rgba(142, 210, 224, .15);",
    ]),
    "extra_tokens_light_attr": "\n      ".join([
        "--tag-homelab: #7C5CBF; --tag-homelab-bg: rgba(124, 92, 191, .12);",
        "--tag-printing3d: #A85A26; --tag-printing3d-bg: rgba(168, 90, 38, .12);",
        "--tag-tooling: #2E6DAE; --tag-tooling-bg: rgba(46, 109, 174, .12);",
        "--tag-systems: #1A7557; --tag-systems-bg: rgba(26, 117, 87, .12);",
        "--tag-networking: #B03E71; --tag-networking-bg: rgba(176, 62, 113, .12);",
        "--tag-cloud: #1C7F97; --tag-cloud-bg: rgba(28, 127, 151, .12);",
    ]),
    "extra_tokens_dark_attr": "\n      ".join([
        "--tag-homelab: #B39DDB; --tag-homelab-bg: rgba(179, 157, 219, .15);",
        "--tag-printing3d: #F5B78E; --tag-printing3d-bg: rgba(245, 183, 142, .15);",
        "--tag-tooling: #90CAF9; --tag-tooling-bg: rgba(144, 202, 249, .15);",
        "--tag-systems: #A5D6C1; --tag-systems-bg: rgba(165, 214, 193, .15);",
        "--tag-networking: #F0A8C4; --tag-networking-bg: rgba(240, 168, 196, .15);",
        "--tag-cloud: #8ED2E0; --tag-cloud-bg: rgba(142, 210, 224, .15);",
    ]),
}

NO_EXTRA_TOKENS = {
    "extra_tokens_base": "",
    "extra_tokens_dark_media": "",
    "extra_tokens_light_attr": "",
    "extra_tokens_dark_attr": "",
}

def build_blog_meta(domain, scheme):
    return {
        "en": {
            "description": "Blog on homelab, self-hosted infrastructure, tooling and more. Articles in progress.",
            "og_url": f"{scheme}://blog.{domain}/",
            "og_locale": "en_US",
            "og_locale_alternate": "fr_FR",
            "canonical_url": f"{scheme}://blog.{domain}/",
        },
        "fr": {
            "description": "Blog sur le homelab, l’infrastructure self-hosted, les outils et plus. Articles en cours de rédaction.",
            "og_url": f"{scheme}://blog.{domain}/fr/",
            "og_locale": "fr_FR",
            "og_locale_alternate": "en_US",
            "canonical_url": f"{scheme}://blog.{domain}/fr/",
        },
    }


def build_projects_meta(domain, scheme):
    return {
        "en": {
            "description": "Projects I build and run: voidnode, khaddict-com, homelab, easypki.",
            "og_url": f"{scheme}://projects.{domain}/",
            "og_locale": "en_US",
            "og_locale_alternate": "fr_FR",
            "canonical_url": f"{scheme}://projects.{domain}/",
        },
        "fr": {
            "description": "Projets que je construis et fais tourner : voidnode, khaddict-com, homelab, easypki.",
            "og_url": f"{scheme}://projects.{domain}/fr/",
            "og_locale": "fr_FR",
            "og_locale_alternate": "en_US",
            "canonical_url": f"{scheme}://projects.{domain}/fr/",
        },
    }


def build_media_meta(domain, scheme):
    return {
        "en": {
            "description": "Personal media gallery hosting icons, wallpapers, homelab videos and assets.",
            "og_url": f"{scheme}://media.{domain}/",
            "og_locale": "en_US",
            "og_locale_alternate": "fr_FR",
            "canonical_url": f"{scheme}://media.{domain}/",
        },
        "fr": {
            "description": "Galerie personnelle hébergeant icônes, fonds d’écran, vidéos et assets du homelab.",
            "og_url": f"{scheme}://media.{domain}/fr/",
            "og_locale": "fr_FR",
            "og_locale_alternate": "en_US",
            "canonical_url": f"{scheme}://media.{domain}/fr/",
        },
    }


BLOG_META = None
PROJECTS_META = None
MEDIA_META = None

NOT_FOUND_DESCRIPTION = "This page doesn't exist."


def build_rss_hrefs(domain, scheme):
    return {
        "en": f"{scheme}://blog.{domain}/feed.xml",
        "fr": f"{scheme}://blog.{domain}/fr/feed.xml",
    }


RSS_HREFS = None


def hreflang_hrefs(site_key):
    """<link rel="alternate" hreflang=...> hrefs for a site's own root, en/fr/
    x-default - same value as lang_switch_hrefs() but keyed for the hreflang
    tags instead of the visible lang-switcher links."""
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
            "title": xml_escape(post["title"][locale]),
            "link": link,
            "pub_date": format_datetime(pub_date),
            "description": xml_escape(post["excerpt"][locale]),
        })
    return items


def lang_switch_hrefs(site_key):
    """Locale-switcher <a> hrefs for lang_mode "url" pages: always the
    subdomain root (with trailing slash), matching the on-disk convention
    that predates this template (the switcher links to the sibling site
    root, not necessarily the current page)."""
    return {
        "lang_switch_fr_href": SITE_URLS["fr"][site_key],
        "lang_switch_en_href": SITE_URLS["en"][site_key] + "/",
    }


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


PAGE_CHOICES = ["www", "vps-fallback", "blog", "projects", "media", "404", "posts", "feed"]


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
        help="Base domain for every self-referential link this build produces - nav, brand "
        "link, lang switcher, canonical/OG/hreflang, icons, RSS - e.g. --domain "
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
    out_root = args.out_dir.resolve()
    only = args.only

    global SITE_URLS, BRAND_ICON_URL, WWW_META, BLOG_META, PROJECTS_META, MEDIA_META, RSS_HREFS
    SITE_URLS = build_site_urls(args.domain, args.scheme)
    BRAND_ICON_URL = f"{args.scheme}://media.{args.domain}/icons/khazix-pc-flat.png"
    WWW_META = build_www_meta(args.domain, args.scheme)
    BLOG_META = build_blog_meta(args.domain, args.scheme)
    PROJECTS_META = build_projects_meta(args.domain, args.scheme)
    MEDIA_META = build_media_meta(args.domain, args.scheme)
    RSS_HREFS = build_rss_hrefs(args.domain, args.scheme)

    # vps-fallback always represents the real public site (that's its whole
    # job during an outage), so its nav/cookie context ignores --domain.
    prod_site_urls = build_site_urls("khaddict.com", "https")

    # domain=.khaddict.com is deliberately a leading-dot cookie domain so the
    # theme cookie is shared across all khaddict.com subdomains; the local
    # equivalent shares it across www/blog/media/projects.<domain> the same
    # way. Secure requires HTTPS - dropped for --scheme http, where the
    # browser would otherwise silently refuse to set the cookie at all.
    cookie_domain = f".{args.domain}"
    cookie_secure_attr = "; Secure" if args.scheme == "https" else ""

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    common = load_i18n("common")
    with open(TEMPLATES / "data" / "posts.yaml", encoding="utf-8") as f:
        posts = yaml.safe_load(f)

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
                brand_href=SITE_URLS[locale]["brand"],
                nav_home_href=SITE_URLS[locale]["home"],
                nav_blog_href=SITE_URLS[locale]["blog"],
                nav_projects_href=SITE_URLS[locale]["projects"],
                nav_media_href=SITE_URLS[locale]["media"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=WWW_META[locale]["description"],
                og_url=WWW_META[locale]["og_url"],
                og_locale=WWW_META[locale]["og_locale"],
                og_locale_alternate=WWW_META[locale]["og_locale_alternate"],
                canonical_url=WWW_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **WWW_EXTRA_TOKENS,
                **lang_switch_hrefs("home"),
                **hreflang_hrefs("home"),
            )

    if only in (None, "vps-fallback"):
        vps_yaml = load_i18n("vps_fallback")
        vps_i18n_all = merged_i18n(common, vps_yaml)
        # vps-fallback has no /fr/ sibling: it ships one lang-agnostic build whose
        # static (pre-JS) markup mirrors what was already on disk (English text,
        # lang="en"), while the runtime I18N object still carries both locales for
        # the cookie-based switcher. The lang-current placeholder is left as "FR"
        # to match the file as it existed before this refactor.
        render(
            env,
            "pages/vps_fallback.html.j2",
            out_root / "vps-fallback/index.html",
            lang="en",
            lang_mode="cookie",
            lang_current="FR",
            i18n=vps_i18n_all["en"],
            i18n_all=vps_i18n_all,
            brand_href=prod_site_urls["en"]["brand"],
            nav_home_href=prod_site_urls["en"]["home"],
            nav_blog_href=prod_site_urls["en"]["blog"],
            nav_projects_href=prod_site_urls["en"]["projects"],
            nav_media_href=prod_site_urls["en"]["media"],
            nav_dashboard_href=prod_site_urls["en"]["dashboard"],
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
                brand_href=SITE_URLS[locale]["home"],
                nav_home_href=SITE_URLS[locale]["home"],
                nav_blog_href=SITE_URLS[locale]["blog"],
                nav_projects_href=SITE_URLS[locale]["projects"],
                nav_media_href=SITE_URLS[locale]["media"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
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
                brand_href=SITE_URLS[locale]["home"],
                nav_home_href=SITE_URLS[locale]["home"],
                nav_blog_href=SITE_URLS[locale]["blog"],
                nav_projects_href=SITE_URLS[locale]["projects"],
                nav_media_href=SITE_URLS[locale]["media"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=PROJECTS_META[locale]["description"],
                og_url=PROJECTS_META[locale]["og_url"],
                og_locale=PROJECTS_META[locale]["og_locale"],
                og_locale_alternate=PROJECTS_META[locale]["og_locale_alternate"],
                canonical_url=PROJECTS_META[locale]["canonical_url"],
                cookie_domain=cookie_domain,
                cookie_secure_attr=cookie_secure_attr,
                **PROJECTS_EXTRA_TOKENS,
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
                brand_href=SITE_URLS[locale]["home"],
                nav_home_href=SITE_URLS[locale]["home"],
                nav_blog_href=SITE_URLS[locale]["blog"],
                nav_projects_href=SITE_URLS[locale]["projects"],
                nav_media_href=SITE_URLS[locale]["media"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
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

    if only in (None, "404"):
        not_found_yaml = load_i18n("404")
        not_found_i18n_all = merged_i18n(common, not_found_yaml)
        # 404.html is a single shared file served across all 4 khaddict.com
        # subdomains (see Helm configmap.yaml / deployment.yaml), not a per-site
        # page like the others, so it only ever gets one "en" render. Its
        # lang-switcher links to the site ROOT's /fr/ (not a same-page fr
        # variant, since a 404 has no page-specific fr content), and its runtime
        # currentLang is detected from location.pathname rather than baked in
        # at build time.
        render(
            env,
            "pages/404.html.j2",
            out_root / "files/shared/404.html",
            lang="en",
            lang_mode="url",
            lang_current="EN",
            i18n=not_found_i18n_all["en"],
            i18n_all=not_found_i18n_all,
            brand_href="/",
            nav_home_href=SITE_URLS["en"]["home"],
            nav_blog_href=SITE_URLS["en"]["blog"],
            nav_projects_href=SITE_URLS["en"]["projects"],
            nav_media_href=SITE_URLS["en"]["media"],
            nav_dashboard_href=SITE_URLS["en"]["dashboard"],
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
        # posts.yaml is data, not translation strings in the i18n sense: it holds
        # the one field (title/excerpt/body/date/tags) that's genuinely unique
        # per blog post, keyed by slug, feeding both blog.html.j2 (the listing's
        # ARTICLES array) and post.html.j2 (this loop) from a single source.
        for slug, post in posts.items():
            post_extra = {
                # {MEDIA} in a post body is a placeholder for the media
                # site's own base URL, resolved here (not by Jinja - post
                # bodies are inserted as opaque strings, never re-parsed as
                # templates) so embedded gallery/video links stay on
                # --domain during a local/preprod build instead of always
                # pointing at prod. Always SITE_URLS["en"]["media"] (no
                # trailing /fr/) regardless of locale: /gallery/ and
                # /videos/ aren't locale-prefixed paths on the media site.
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
                    brand_href=SITE_URLS[locale]["home"],
                    nav_home_href=SITE_URLS[locale]["home"],
                    nav_blog_href=SITE_URLS[locale]["blog"],
                    nav_projects_href=SITE_URLS[locale]["projects"],
                    nav_media_href=SITE_URLS[locale]["media"],
                    nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                    brand_icon_src=BRAND_ICON_URL,
                    meta_description=post["excerpt"][locale],
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
                    cookie_domain=cookie_domain,
                    cookie_secure_attr=cookie_secure_attr,
                    **BLOG_EXTRA_TOKENS,
                )

    if only in (None, "feed"):
        # The feed is derived entirely from posts.yaml (the same data backing the
        # blog listing and post pages), one per locale to match the rest of the
        # site's EN/FR split.
        for locale, out_rel in (("en", "files/blog/feed.xml"), ("fr", "files/blog/fr/feed.xml")):
            render(
                env,
                "pages/feed.xml.j2",
                out_root / out_rel,
                channel_link=BLOG_META[locale]["canonical_url"],
                rss_href=RSS_HREFS[locale],
                channel_description=xml_escape(BLOG_META[locale]["description"]),
                language="fr-fr" if locale == "fr" else "en-us",
                items=build_feed_items(posts, locale, args.domain, args.scheme),
            )


if __name__ == "__main__":
    main()
