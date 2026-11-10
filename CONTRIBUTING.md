# Contributing

## Branches

`main` is always releasable. Work happens on short-lived branches merged through pull requests:

| Prefix | For |
| --- | --- |
| `feat/` | a new feature (`feat/live-counter-buy`) |
| `fix/` | a bug fix (`fix/nbsp-item-links`) |
| `docs/` | documentation only |
| `refactor/` | code changes without behaviour change |
| `test/` | tests only |
| `chore/` | tooling, dependencies |

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, imperative mood, lower case,
no trailing period.

```
feat(report): show creator video tips in the counter view
fix(textlinks): match item names containing non-breaking spaces
docs: explain the analysis method versioning
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`.

## Analysis method changes

Any change to how information is gathered or what is written on the pages, even a small one, needs a new entry in
`data/changelog.json` with a precise `todo`. Existing pages then show what changed and offer a targeted update.

## Checks

GitHub Actions runs the same checks on every push and pull request; run them locally before pushing:

```sh
./check.sh   # ruff (when installed) + unit tests
```

Pages generated before and after a refactor should be identical: regenerate a few with `scripts/report.py` and
compare them.
