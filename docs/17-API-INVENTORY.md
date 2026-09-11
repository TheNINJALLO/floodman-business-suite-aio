# API inventory

The generated scanner found 304 FastAPI route decorators in the custom source:

| Service | Route decorators |
|---|---:|
| Floodman Office | 219 |
| Local Lab | 46 |
| Orchestrator | 27 |
| Competitor Intelligence | 10 |
| Messaging AI | 2 |

The complete machine-readable list is in:

```text
docs/generated/API_ROUTE_INVENTORY.csv
```

Major route families include:

```text
/mobile-api/v1/*       native Android and iOS operations
/office/*              staff Office pages and actions
/customer/*            public tokenized customer actions
/internal/v1/*         signed internal service calls
/api/*                  provider and service APIs
/health/*               readiness and liveness
```

Do not assume every decorator is public. Nginx and the external HTTPS proxy access rules define the exposure boundary.
