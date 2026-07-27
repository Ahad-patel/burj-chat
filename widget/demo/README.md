# Host collision harness

`index.html` reproduces the real host environment: burjconstructions.com's own
`bootstrap.min.css`, `animate.min.css`, `style.css`, and `burj.css`, plus
jQuery 3.5.1 and a block of deliberately hostile overrides.

Those vendor files are **not committed** — they are the client's assets and add
~340 KB of third-party CSS to the repo. Fetch them once:

```sh
cd widget/demo
for f in bootstrap.min.css animate.min.css style.css burj.css; do
  curl -sSO "https://burjconstructions.com/css/$f"
done
curl -sSo jquery.min.js https://code.jquery.com/jquery-3.5.1.min.js
```

Then, from `widget/`:

```sh
npm run verify     # build + headless-Chromium isolation checks
open demo/index.html   # or eyeball it
```

Testing against a blank sandbox proves nothing. The question is whether the
widget survives *this* cascade — and the harness includes a control assertion
that the hostile CSS genuinely wrecks an unprotected element, so the isolation
checks cannot pass by the overrides silently failing to apply.
