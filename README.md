# khaddict-com

Static site content (HTML/CSS/JS) for the khaddict.com site family: `www`, `blog`, `images`, `projects`, plus the shared 404 page and a standalone VPS fallback page. Pages are authored as Jinja2 templates and rendered to static HTML by `build.py`; the rendered output is what actually ships, but it isn't committed. `templates/` is the only source of truth.

This repo holds no infrastructure. It's packaged as a Helm chart (`Chart.yaml` + `files/`) published to `oci://ghcr.io/khaddict/charts` and pulled in as a subchart dependency by [`voidnode`](https://github.com/khaddict/voidnode)'s `argocd/apps/khaddict` chart, which reads the rendered files via `(index .Subcharts "khaddict-com").Files.Get`.

## Structure

```
Chart.yaml               # content chart, no Kubernetes templates of its own
build.py                 # renders templates/ -> files/** and vps-fallback/index.html
requirements.txt         # jinja2, pyyaml
templates/
  partials/              # shared chrome: theme cookie, header/nav, status widget, footer, responsive CSS
  pages/                 # one template per page type (www, blog, projects, images, 404, vps_fallback, post, feed)
  data/
    i18n/                # translation strings per page type, en + fr
    posts.yaml           # one entry per blog post slug: date, tags, title/excerpt/body in en+fr
files/
  www/ blog/ images/ projects/   # generated index.html (+ fr/index.html) land here, all gitignored
  blog/posts/<slug>/     # generated per-post pages, gitignored
  blog/feed.xml          # generated RSS feed (+ fr/feed.xml), gitignored
  shared/                # 404 page (generated, gitignored) plus hand-maintained default.conf, security-headers.conf, robots.txt
  <site>/security.txt, sitemap.xml   # hand-maintained, not generated
images-build/            # Docker build context for the images-khaddict gallery/icons image
                         # (excluded from the Helm chart via .helmignore, published separately)
vps-fallback/            # generated 503 page for the VPS-side fallback (gitignored), see below
```

Every generated page shares the same header, footer, theme toggle (light by default on first visit), language switcher (FR/EN, `/fr/` URL siblings everywhere except vps-fallback, which stays cookie-based since it has no sibling), and live status widget, all defined once in `templates/partials/` instead of being duplicated by hand. The blog also gets an RSS feed link in its footer.

## Building

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 build.py
```

This renders every page to its real path (`files/www/index.html`, `vps-fallback/index.html`, etc., all gitignored, never committed). Two useful flags:

- `--out-dir <dir>`: render to a different directory instead of the real paths (e.g. `--out-dir _preview`, already gitignored), for previewing changes without touching what a local Helm test or a manual deploy would pick up.
- `--only <page>`: render just one page instead of the whole site. Choices: `www`, `vps-fallback`, `blog`, `projects`, `images`, `404`, `posts`, `feed`.

## Publishing

Two independent CI workflows:

- **`publish-chart.yaml`** (push to `main`, paths `Chart.yaml`/`files/**`/`templates/**`/`build.py`/`requirements.txt`): installs the Python deps, runs `build.py` to regenerate the site fresh, then packages and pushes to `oci://ghcr.io/khaddict/charts`. Version is `0.1.$(git rev-list --count HEAD)`, the repo's total commit count at build time rather than a sequential publish counter, so it can jump by more than 1 between two publishes if unrelated commits (e.g. Renovate bumping an action version) landed in between.
- **`templates-build-check.yaml`** (PR and push to `main`, paths `templates/**`/`build.py`/`requirements.txt`): runs `build.py` and fails if it errors. A smoke test that templates still render, nothing more (there's no committed output to compare against).
- **`images-khaddict.yaml`** builds and pushes the `images-build/` Docker image (gallery photos + tech-stack icons, resized and stickered at build time) to `ghcr.io/khaddict/images-khaddict`, tagged with the commit's short SHA and `latest`.

Neither workflow writes back to `voidnode`. Renovate watches `voidnode`'s `Chart.yaml` dependency version and the `images-khaddict` image tag in `values.yaml`, and opens a PR there when either one moves. This repo has its own `.github/renovate.jsonc` to keep the Dockerfile base images and the GitHub Actions versions in `.github/workflows/` current.

## Adding a blog post

Add an entry to `templates/data/posts.yaml` (slug key, `date`/`tags`/`title`/`excerpt`/`body` in `en` + `fr`). The listing, the post's own page, and the RSS feed are all driven from this one file, in both languages, automatically. No template edits needed.

## Adding a new site

More involved than a blog post, since it needs its own template, data, and Kubernetes wiring:

1. Add `templates/pages/<name>.html.j2` and `templates/data/i18n/<name>.yaml` (see `projects.html.j2`/`projects.yaml` as a starting point).
2. Wire it into `build.py`: load its i18n yaml, add a per-locale metadata dict (description/og/canonical URLs), add a render loop for `en`/`fr`.
3. Add `files/<name>/security.txt` (hand-maintained, not generated) and, if it needs one, a `sitemap.xml`.
4. Add the nav link to `templates/partials/header.html.j2`, the one shared partial every page includes, so this is a single edit.
5. In `voidnode`, add the new site to `argocd/apps/khaddict/values.yaml`'s `sites:` list. Deployment/Service/HTTPRoute/ConfigMap are generated from that list already, no template changes needed there.
6. `voidnode` also needs: a DNS CNAME, a `revproxy` HAProxy ACL + backend, the new hostname added to the VPS-side nginx configs and the fallback TLS cert's SAN list. See `documentation/KHADDICT-VPS/KHADDICT-VPS.md` in `voidnode`.

## vps-fallback

`vps-fallback/index.html` is the standalone 503 page served from a separate fallback VPS. It's not part of the Helm chart (excluded via `.helmignore`) and not wired into any CI workflow, since it's deployed by hand. After editing `templates/pages/vps_fallback.html.j2` (or any shared partial), regenerate it locally with:

```
.venv/bin/python3 build.py --only vps-fallback
```

then deploy the resulting `vps-fallback/index.html` to the VPS however you currently do that; this repo doesn't automate that last step.

## Testing locally

`helm template`/`helm dependency update` need the real `files/**` paths to exist on disk, so run `.venv/bin/python3 build.py` first (see "Building" above), otherwise `.Files.Get` in `voidnode`'s chart has nothing to read.

`helm dependency update` also needs a real published chart to resolve `oci://ghcr.io/khaddict/charts`. To test a local change to this repo against `voidnode` before pushing, temporarily point `voidnode`'s `argocd/apps/khaddict/Chart.yaml` dependency at a local path:

```yaml
dependencies:
  - name: khaddict-com
    version: "0.1.0"
    repository: "file:///path/to/khaddict-com"
```

then `helm dependency update argocd/apps/khaddict` and `helm template` from `voidnode`. Revert to the `oci://` repository before committing.
