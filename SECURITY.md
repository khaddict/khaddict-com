# Security

This is a static site generator with no server-side runtime of its own. Everything here is about the build pipeline and the CI that publishes it. Update this file whenever that changes, not just when a new mechanism is added.

## Templating and XSS

`build.py` renders with Jinja2's `autoescape=True`. Every `{{ var }}` is HTML-escaped by default; the handful of strings that genuinely need to render as markup are marked `| safe` explicitly:

- `hero.title`, `wall.dropZone` (`templates/data/i18n/www.yaml`)
- `projects.title`, `deploy.title` (`templates/data/i18n/projects.yaml`)
- `post.body` (`templates/data/posts.yaml`, injected into the i18n dict in `build.py`)

The client-side language switcher (`applyLanguage()`, duplicated per page template) mirrors this: it uses `textContent` by default and only reaches for `innerHTML` on the same explicit key list (`HTML_I18N_KEYS`). If you add a 6th `| safe` string, add its key to that set in every page template that could render it. A mismatch here is silent (no error, the string just renders as literal escaped text instead of markup).

None of this is exploitable today because every string that reaches a template (i18n YAML, `posts.yaml`) is repo-committed, operator-authored content. The moment this pipeline accepts anything from a less-trusted source (a community post PR, an imported comment feed) without explicit escaping, that source becomes a stored-XSS vector across the whole site. Treat this list as the thing to re-check before adding any such feature.

Inline `<script>` blocks interpolate values via the `js_str()` macro (`templates/partials/js_str.j2`), which wraps Jinja's `tojson` filter and marks its own output `| safe`. `tojson` already produces script-safe output (it escapes `<`, `>`, `&` for HTML-embedding), so a second escaping pass would double-encode it. Don't remove that `| safe`, and don't interpolate a JS string any other way (`'{{ var }}'` directly) unless the value is guaranteed to never contain a quote. The two direct interpolations that do this today (`{{ lang }}`, `{{ api_base_url }}`) are safe only because their values are fixed to `en`/`fr` and a plain HTTPS URL.

## CSP

`files/shared/security-headers.conf` sets a real CSP: `object-src 'none'`, `frame-ancestors 'self'`, `base-uri 'self'`, a scoped `connect-src`. It also has `'unsafe-inline'` on `script-src` and `style-src`, which is required by the many inline `<script>`/`<style>` blocks per page and means CSP would **not** block a successful XSS via the mechanism above. It's defense-in-depth for other vectors, not a backstop for this one.

## CI / cross-repo trust

`publish-chart.yaml` and `media-khaddict.yaml` each split into two jobs:

1. **`publish`/`build`**: runs this repo's own code (`build.py`, or a Docker build). No cross-repo credential is available here.
2. **`bump-voidnode`**: `needs:` the first job, receives only a plain version string as input, and is gated with `if: github.ref == 'refs/heads/main'` so a manual `workflow_dispatch` on any other branch can't reach it. It checks out `voidnode` with a fine-grained PAT (`VOIDNODE_REPO_TOKEN`, `Contents: Read and write`, scoped to that one repo) and **opens a PR**, never pushes directly to `main`. Every bump still needs a human merge.

This split means a compromised `build.py` (or a malicious dependency pulled in by `pip install -r requirements.txt`) can't reach the token, since it never runs in the same job. If this repo ever accepts outside contributors, revisit whether `workflow_dispatch` should be restricted further (branch protection alone doesn't cover it, since dispatch runs aren't PRs).

Renovate does **not** track the `khaddict-com` chart or the `media-khaddict` image inside `voidnode` (disabled on that side). These two workflows are the sole source of those bumps now, to avoid two mechanisms racing on the same two files.

## Reporting an issue

Personal project, single maintainer. If you find something, open a GitHub Security Advisory on this repo rather than a public issue.
