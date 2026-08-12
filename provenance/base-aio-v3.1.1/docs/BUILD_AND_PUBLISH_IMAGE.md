# Build and Publish the AIO Image

The egg expects:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1
```

## Repository layout

Create a GitHub repository such as:

```text
TheNINJALLO/floodman-business-suite-aio
```

Upload the contents of this package so the repository root contains:

```text
.github/
image/
scripts/
docs/
egg-floodman-business-suite-aio.json
README.md
VERSION
THIRD_PARTY_NOTICES.md
```

## Run the workflow

1. Open the repository on GitHub.
2. Open **Actions**.
3. Select **Build Floodman Pterodactyl AIO**.
4. Select **Run workflow**.
5. Wait for validation and the AMD64 image build.
6. Open the repository package settings and make the GHCR package public for the simplest test deployment.

The workflow publishes:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1
ghcr.io/theninjallo/floodman-business-suite-aio:latest-test
```

Do not put a GitHub personal access token into an editable Pterodactyl startup variable. When the package remains private, configure registry credentials in Wings instead.
