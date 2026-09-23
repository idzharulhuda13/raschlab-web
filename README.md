---
title: RaschLab
emoji: chart_with_upwards_trend
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

This is the web app for RaschLab, providing dichotomous Rasch item analysis powered by the engine repo raschlab.

## Local development

Local runs enable the interactive API docs with APP_ENV=dev; without it the app behaves as production and serves no docs.

```bash
uv venv
uv pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

## Deployment

Deployable as a Hugging Face Space using the Docker SDK. Configure secrets `DATABASE_URL`, `HF_TOKEN`, `RESEND_API_KEY`, and `SESSION_SECRET` in Space settings and never commit them to the repository.
