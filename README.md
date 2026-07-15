# khaddict-com

Static site content (HTML/CSS/JS) for the khaddict.com site family: `www`, `blog`, `images`, `projects`, plus the shared 404 page used by all of them.

This repo holds no infrastructure. It's packaged as a Helm chart with no templates, just `Chart.yaml` + `files/`, published to `oci://ghcr.io/khaddict/charts` and pulled in as a subchart dependency by [`voidnode`](https://github.com/khaddict/voidnode)'s `argocd/apps/khaddict` chart, which reads the actual files via `(index .Subcharts "khaddict-com").Files.Get`.

## Structure

```
Chart.yaml             # content chart, no templates/
files/
  www/                 # khaddict.com
  blog/                # blog.khaddict.com
  images/              # images.khaddict.com
  projects/            # projects.khaddict.com
  shared/              # 404 page, security headers, robots.txt, nginx default.conf
images-build/          # Docker build context for the images-khaddict gallery/icons image
                       # (excluded from the Helm chart via .helmignore, published separately)
vps-fallback/          # standalone 503 page for the VPS-side fallback, deployed manually,
                       # not part of the Helm chart (see voidnode/documentation/KHADDICT-VPS)
```

Every site page shares the same header, footer, theme toggle (cookie-persisted), language switcher (FR/EN, defaults to English), and live status widget, hand-rolled in vanilla HTML/CSS/JS with no build step. Adding a new page means copying an existing `files/<site>/index.html` as a starting point and editing it in place, since there's no shared component system to update in one spot.

## Publishing

Two independent CI workflows, both triggered on push to `main`:

- **`publish-chart.yaml`** packages `files/` (and `Chart.yaml`) whenever they change, and pushes to `oci://ghcr.io/khaddict/charts` with version `0.1.<run number>`.
- **`images-khaddict.yaml`** builds and pushes the `images-build/` Docker image (gallery photos + tech-stack icons, resized and stickered at build time) to `ghcr.io/khaddict/images-khaddict`, tagged with the commit's short SHA and `latest`.

Neither workflow writes back to `voidnode`. Renovate watches `voidnode`'s `Chart.yaml` dependency version and the `images-khaddict` image tag in `values.yaml`, and opens a PR there when either one moves. This repo has its own `renovate.json` (plain `config:recommended`) to keep the Dockerfile base images (`alpine`, `nginx`) and the GitHub Actions versions in `.github/workflows/` current.

## Adding a new site

1. Create `files/<name>/index.html` (and `security.txt`). Easiest starting point: copy an existing site's `index.html` for the shared header/footer/theme/i18n scaffolding, then replace the page-specific content.
2. Add the nav link to the shared topnav in every existing `files/*/index.html` and `files/shared/404.html`.
3. Push. `publish-chart.yaml` republishes the chart.
4. In `voidnode`, add the new site to `argocd/apps/khaddict/values.yaml`'s `sites:` list. Deployment/Service/HTTPRoute/ConfigMap are generated automatically from that list, no template changes needed.
5. `voidnode` also needs: a DNS CNAME, a `revproxy` HAProxy ACL + backend, the new hostname added to the VPS-side nginx configs and the fallback TLS cert's SAN list. See `documentation/KHADDICT-VPS/KHADDICT-VPS.md` in `voidnode`.

## Testing locally

`helm dependency update` needs a real published chart to resolve `oci://ghcr.io/khaddict/charts`. To test a local change to this repo against `voidnode` before pushing, temporarily point `voidnode`'s `argocd/apps/khaddict/Chart.yaml` dependency at a local path:

```yaml
dependencies:
  - name: khaddict-com
    version: "0.1.0"
    repository: "file:///path/to/khaddict-com"
```

then `helm dependency update argocd/apps/khaddict` and `helm template` from `voidnode`. Revert to the `oci://` repository before committing.
