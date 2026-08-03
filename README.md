# BlackBox GitHub Pages documentation

This folder contains the static installation/documentation site for BlackBox.

## Recommended layout

Place this folder in the repository root:

```text
your-repository/
├── docs/
│   ├── index.html
│   └── assets/
│       ├── style.css
│       └── app.js
└── .github/
    └── workflows/
        └── pages.yml
```

## Important

Before publishing, replace `YOUR_GITHUB_REPOSITORY_URL` in `docs/index.html` with the real clone URL.

The documentation intentionally does not contain real secrets, JWTs, or API keys.

## Enable GitHub Pages

In GitHub:

1. Open the repository.
2. Go to Settings → Pages.
3. Set the source to GitHub Actions.
4. Push to `main`.
5. Open the Pages URL shown by GitHub.

GitHub's Pages documentation describes the Actions-based deployment flow.
