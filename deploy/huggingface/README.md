---
title: Alpha Lab Simulator
emoji: 📈
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Bilingual, bounded AI alpha learning simulations
---

# Alpha Lab Simulator

A Chinese/English Streamlit teaching app for the path from historical features
and future-return labels to model training, held-out evaluation and constrained
portfolio weights. Synthetic teaching observations are explicitly labeled.
The primary input is a bounded OHLCV CSV supplied by a visitor. An optional
online mode retrieves public Yahoo daily history for 3–8 US stocks/ETFs and a
benchmark, with explicit source and adjustment metadata.

Deployment status and verified public entrypoints are recorded in the
[project deployment guide](https://github.com/Rexmiao/alpha-trading-lab/blob/main/docs/HUGGINGFACE_DEPLOYMENT.md).
The package manifest verifies source integrity; container startup and successful
page interactions are checked separately. The container build checks NumPy,
pandas and PyArrow table conversion before publishing the image.

## Scope

- Run bounded simulations and public history requests only after an explicit user action.
- Download a session-only online price CSV snapshot and source JSON for repeatability; provider errors are explicit and never replaced with synthetic data.
- Compare Ridge, MLP, resampling and conditional-DDPM augmentation.
- Explore four daily rules or a separate 5-minute momentum/trend page with
  UTC bar-start CSV inputs, exchange-calendar RTH validation, daily aggregation
  and bilingual mathematical explanations. Intraday fills are OHLC proxies;
  synthetic and uploaded data remain explicitly separated.
- Keep uploaded CSV and results in the current session; the package contains no
  saved market data, local research results, models, credentials or account data.
- No connection to a desktop broker, no account access and no order submission.
  A cloud container cannot reach a user's desktop loopback service.

Uploading a CSV sends it to the Space's Python process for analysis. It is not
browser-only computation. Supply only standard daily or 5-minute OHLCV content that you
intend the service to process; do not include accounts or credentials.

## Hugging Face setup

Create a **Docker** Space, then upload all files from the generated bundle at
the Space repository root, preserving `hf_space/` and `research/` directories.
Do not upload the parent research repository or a ZIP as a single runtime file.
The Dockerfile runs Streamlit on `0.0.0.0:7860` as non-root UID 1000, with CPU
math-library threads limited to one. No broker key or HF token is needed by
the running app.

Current Hugging Face documentation requires a paid personal PRO plan to create
a new Docker Space on CPU Basic. CPU Basic itself has no hourly hardware charge;
that does not make new Docker Space creation available to every free account.
Account eligibility and billing choices must be checked before creation.
No account login, payment or Space creation is performed by this package.

CPU Basic can sleep after inactivity. Runtime disk is ephemeral: restarts can
lose files and sessions. This demo does not require persistent storage and must
not treat local container files as a durable research archive.

## Optional local Docker check

Run these commands inside the generated bundle, if Docker is installed:

```sh
docker build -t alpha-lab-simulator .
docker run --rm -p 7860:7860 alpha-lab-simulator
```

Then visit `http://localhost:7860`. A successful local container check still
does not constitute a Hugging Face deployment.

## Sources and deployment requirements

- [Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker)
- [Streamlit Docker recommendation](https://huggingface.co/docs/hub/spaces-sdks-streamlit)
- [Account and hardware requirements](https://huggingface.co/docs/hub/spaces-overview)
- [Ephemeral storage](https://huggingface.co/docs/hub/spaces-storage)
- [Source project](https://github.com/Rexmiao/alpha-trading-lab)

The GitHub Pages teaching website remains independent of this optional Python
app. Neither synthetic results nor one historical test establish a trading edge.
