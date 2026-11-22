# 11 - Project Understanding Validation

| Check | Method | Result |
|---|---|---|
| Python modules parse | `ast.parse` on all 5 `.py` files (venv interpreter, isolated mode, no bytecode written) | Pass |
| Dependencies | Compared every pin in `requirements.txt` with installed `.venv` versions | 22/22 match |
| Unused dependencies | Searched imports for 6 suspect packages | None imported (F-25) |
| Frontend wiring | Every `getElementById` ID in `script.js` exists in `index.html` | Pass |
| API surface | Cross-read `app.py`, `script.js`, README | Matches, except README "create or resume" wording |
| DB schema | Table/key definitions read from installed `langgraph-checkpoint-postgres` | Matches doc 05 |
| Secrets hygiene | `git ls-files`, `git log --all -- .env .env.production`, `.gitignore`, `.dockerignore` | Not tracked, never committed, excluded from image |
| `.env` content | Only variable names printed; values redacted | No secret exposed |
| Deployment files | Read Dockerfile, both compose files, deploy script, Nginx fragments | Consistent with deploy README |

## Not verified (by design)

The application was not started, no external API/LLM/MCP/DB call was made, no
container was built, and nothing was deployed. Therefore behaviours marked
**P** (F-03 exploit path, F-08, F-14 cost, F-19) and runtime claims such as
latency or exact error text are code-reading conclusions. Static review of
`demo.excalidraw`, the manual `.docx` and `Project Details.xlsx` was skipped.
The truncated first prompt meant no instructions beyond Phase 5 were seen
until the follow-up.
