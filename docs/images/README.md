# Images used by the root README

`banner.svg` is committed and needs nothing from you.

The four screenshots below are referenced by the root `README.md` and are **not
in the repository yet**. Until they are added, GitHub shows a broken-image icon
in their place — so either drop them in, or delete those lines from the README.

Capture them at **1440×900**, save as PNG, and keep the exact filenames.

| File | What to capture | Where |
|---|---|---|
| `demo.gif` | The whole loop in ~15 s: upload a CSV → type a question → chart appears → drag it onto the dashboard | Record the browser window only, not the whole desktop |
| `chat-to-chart.png` | The chat panel beside a finished chart, with the answer text visible | `/dashboard` after one question |
| `dashboard.png` | Three or four charts arranged on the canvas | `/dashboard` |
| `connections.png` | Settings → Connections with a generated link on screen | `/settings#connections` |

## Two rules for these

**Use `test-data/sales-retail/tips.csv` or `general-testing/titanic.csv`.** They are
in the repository, so anyone reading the README can reproduce exactly what the
screenshot shows.

**Never screenshot a real connection key.** `connections.png` should be taken
*after* pressing "Done — hide it", or with the key blurred. A key pasted into a
public README is a live credential until someone revokes it.

For the GIF, [ScreenToGif](https://www.screentogif.com/) (Windows) or
[Kap](https://getkap.co/) (macOS) both export small files. Keep it under 5 MB —
GitHub will render it inline, and anything larger is slow on a phone.
