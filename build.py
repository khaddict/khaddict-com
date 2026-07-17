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

# The live site links the brand icon straight to images.khaddict.com. The
# vps-fallback page is shown precisely when the homelab (and therefore
# images.khaddict.com) is unreachable, so it gets its own copy inlined as a
# base64 data URI instead, sized down from images-build/images/icons/khazix-pc-flat.png.
BRAND_ICON_URL = "https://images.khaddict.com/icons/khazix-pc-flat.png"


def fallback_icon_data_uri():
    data = (ASSETS_DIR / "vps-fallback-icon.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

LOCALES = ("en", "fr")

# Per-locale site URLs. These aren't translation strings (they don't come from
# the i18n yaml / the runtime I18N JS object) but they do vary per locale for
# pages built with lang_mode "url", where every khaddict.com subdomain has a
# /fr/ sibling.
SITE_URLS = {
    "en": {
        "brand": "/",
        "home": "https://khaddict.com",
        "blog": "https://blog.khaddict.com",
        "projects": "https://projects.khaddict.com",
        "images": "https://images.khaddict.com",
        "dashboard": "https://dashboard.khaddict.com",
    },
    "fr": {
        "brand": "/fr/",
        "home": "https://khaddict.com/fr/",
        "blog": "https://blog.khaddict.com/fr/",
        "projects": "https://projects.khaddict.com/fr/",
        "images": "https://images.khaddict.com/fr/",
        "dashboard": "https://dashboard.khaddict.com",
    },
}

WWW_META = {
    "en": {
        "description": "Personal space dedicated to homelab, self-hosted infrastructure and code.",
        "og_url": "https://khaddict.com",
        "og_locale": "en_US",
        "og_locale_alternate": "fr_FR",
        "canonical_url": "https://khaddict.com/",
    },
    "fr": {
        "description": "Espace personnel dédié au homelab, à l’infrastructure self-hosted et au code.",
        "og_url": "https://khaddict.com/fr/",
        "og_locale": "fr_FR",
        "og_locale_alternate": "en_US",
        "canonical_url": "https://khaddict.com/fr/",
    },
}

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

BLOG_META = {
    "en": {
        "description": "Blog on homelab, self-hosted infrastructure, tooling and more. Articles in progress.",
        "og_url": "https://blog.khaddict.com/",
        "og_locale": "en_US",
        "og_locale_alternate": "fr_FR",
        "canonical_url": "https://blog.khaddict.com/",
    },
    "fr": {
        "description": "Blog sur le homelab, l’infrastructure self-hosted, les outils et plus. Articles en cours de rédaction.",
        "og_url": "https://blog.khaddict.com/fr/",
        "og_locale": "fr_FR",
        "og_locale_alternate": "en_US",
        "canonical_url": "https://blog.khaddict.com/fr/",
    },
}

PROJECTS_META = {
    "en": {
        "description": "Projects I build and run: voidnode, khaddict-com, homelab, easypki.",
        "og_url": "https://projects.khaddict.com/",
        "og_locale": "en_US",
        "og_locale_alternate": "fr_FR",
        "canonical_url": "https://projects.khaddict.com/",
    },
    "fr": {
        "description": "Projets que je construis et fais tourner : voidnode, khaddict-com, homelab, easypki.",
        "og_url": "https://projects.khaddict.com/fr/",
        "og_locale": "fr_FR",
        "og_locale_alternate": "en_US",
        "canonical_url": "https://projects.khaddict.com/fr/",
    },
}

IMAGES_META = {
    "en": {
        "description": "Personal image gallery hosting icons, wallpapers and homelab assets.",
        "og_url": "https://images.khaddict.com/",
        "og_locale": "en_US",
        "og_locale_alternate": "fr_FR",
        "canonical_url": "https://images.khaddict.com/",
    },
    "fr": {
        "description": "Galerie personnelle hébergeant icônes, fonds d’écran et assets du homelab.",
        "og_url": "https://images.khaddict.com/fr/",
        "og_locale": "fr_FR",
        "og_locale_alternate": "en_US",
        "canonical_url": "https://images.khaddict.com/fr/",
    },
}

NOT_FOUND_DESCRIPTION = "This page doesn't exist."

RSS_HREFS = {
    "en": "https://blog.khaddict.com/feed.xml",
    "fr": "https://blog.khaddict.com/fr/feed.xml",
}


def build_feed_items(posts, locale):
    items = []
    for slug, post in sorted(posts.items(), key=lambda kv: kv[1]["date"], reverse=True):
        pub_date = datetime.strptime(post["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        link = f"https://blog.khaddict.com/{'fr/' if locale == 'fr' else ''}posts/{slug}/"
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


PAGE_CHOICES = ["www", "vps-fallback", "blog", "projects", "images", "404", "posts", "feed"]


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
    args = parser.parse_args()
    out_root = args.out_dir.resolve()
    only = args.only

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
                nav_images_href=SITE_URLS[locale]["images"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=WWW_META[locale]["description"],
                og_url=WWW_META[locale]["og_url"],
                og_locale=WWW_META[locale]["og_locale"],
                og_locale_alternate=WWW_META[locale]["og_locale_alternate"],
                canonical_url=WWW_META[locale]["canonical_url"],
                **WWW_EXTRA_TOKENS,
                **lang_switch_hrefs("home"),
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
            brand_href=SITE_URLS["en"]["brand"],
            nav_home_href=SITE_URLS["en"]["home"],
            nav_blog_href=SITE_URLS["en"]["blog"],
            nav_projects_href=SITE_URLS["en"]["projects"],
            nav_images_href=SITE_URLS["en"]["images"],
            nav_dashboard_href=SITE_URLS["en"]["dashboard"],
            brand_icon_src=fallback_icon_data_uri(),
            meta_description=vps_i18n_all["en"]["error.message"],
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
                nav_images_href=SITE_URLS[locale]["images"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=BLOG_META[locale]["description"],
                og_url=BLOG_META[locale]["og_url"],
                og_locale=BLOG_META[locale]["og_locale"],
                og_locale_alternate=BLOG_META[locale]["og_locale_alternate"],
                canonical_url=BLOG_META[locale]["canonical_url"],
                rss_href=RSS_HREFS[locale],
                **BLOG_EXTRA_TOKENS,
                **lang_switch_hrefs("blog"),
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
                nav_images_href=SITE_URLS[locale]["images"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=PROJECTS_META[locale]["description"],
                og_url=PROJECTS_META[locale]["og_url"],
                og_locale=PROJECTS_META[locale]["og_locale"],
                og_locale_alternate=PROJECTS_META[locale]["og_locale_alternate"],
                canonical_url=PROJECTS_META[locale]["canonical_url"],
                **PROJECTS_EXTRA_TOKENS,
                **lang_switch_hrefs("projects"),
            )

    if only in (None, "images"):
        images_yaml = load_i18n("images")
        images_i18n_all = merged_i18n(common, images_yaml)
        for locale, out_rel in (("en", "files/images/index.html"), ("fr", "files/images/fr/index.html")):
            render(
                env,
                "pages/images.html.j2",
                out_root / out_rel,
                lang=locale,
                lang_mode="url",
                lang_current=locale.upper(),
                i18n=images_i18n_all[locale],
                i18n_all=images_i18n_all,
                brand_href=SITE_URLS[locale]["home"],
                nav_home_href=SITE_URLS[locale]["home"],
                nav_blog_href=SITE_URLS[locale]["blog"],
                nav_projects_href=SITE_URLS[locale]["projects"],
                nav_images_href=SITE_URLS[locale]["images"],
                nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                brand_icon_src=BRAND_ICON_URL,
                meta_description=IMAGES_META[locale]["description"],
                og_url=IMAGES_META[locale]["og_url"],
                og_locale=IMAGES_META[locale]["og_locale"],
                og_locale_alternate=IMAGES_META[locale]["og_locale_alternate"],
                canonical_url=IMAGES_META[locale]["canonical_url"],
                **NO_EXTRA_TOKENS,
                **lang_switch_hrefs("images"),
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
            nav_images_href=SITE_URLS["en"]["images"],
            nav_dashboard_href=SITE_URLS["en"]["dashboard"],
            brand_icon_src=BRAND_ICON_URL,
            meta_description=NOT_FOUND_DESCRIPTION,
            lang_switch_fr_href="/fr/",
            lang_switch_en_href="/",
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
                locale: {
                    "title.post": f"{post['title'][locale]} | khaddict blog",
                    "post.title": post["title"][locale],
                    "post.body": post["body"][locale],
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
                    nav_images_href=SITE_URLS[locale]["images"],
                    nav_dashboard_href=SITE_URLS[locale]["dashboard"],
                    brand_icon_src=BRAND_ICON_URL,
                    meta_description=post["body"][locale],
                    og_url=f"https://blog.khaddict.com/{'fr/' if locale == 'fr' else ''}posts/{slug}/",
                    og_locale="fr_FR" if locale == "fr" else "en_US",
                    og_locale_alternate="en_US" if locale == "fr" else "fr_FR",
                    canonical_url=f"https://blog.khaddict.com/{'fr/' if locale == 'fr' else ''}posts/{slug}/",
                    lang_switch_fr_href=f"https://blog.khaddict.com/fr/posts/{slug}/",
                    lang_switch_en_href=f"https://blog.khaddict.com/posts/{slug}/",
                    rss_href=RSS_HREFS[locale],
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
                items=build_feed_items(posts, locale),
            )


if __name__ == "__main__":
    main()
