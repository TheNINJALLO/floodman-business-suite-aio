# Third-party boundaries

This release contains original orchestration, messaging and monitoring code designed to communicate with separately deployed products and external APIs.

- **Ever Gauzy:** AGPL-3.0 upstream. Keep stock Gauzy isolated behind its API where practical. Review source-availability and commercial licensing implications before deep modifications or distribution.
- **Documenso:** AGPL-3.0 upstream. Keep it isolated as a signing service where practical. Review source-availability and enterprise/commercial requirements before white-labeling or modifying it.
- **Square APIs:** governed by Square developer and seller terms. Square remains the payment and card-data environment.
- **Twilio:** governed by Twilio terms, messaging policies, carrier rules and A2P registration requirements. Floodman remains responsible for consent, content and use.
- **OpenAI API:** optional for customer-message classification and competitor analysis. Keep keys server-side and follow Floodman's approval, privacy and retention policy.
- **TheNINJALLO/Ai-apps:** Apache-2.0 repository reviewed for always-on agents, customer-support retrieval, trust-gated workflows, competitor intelligence and sales-intelligence patterns. This production implementation is a clean service architecture rather than the demonstration Streamlit application.

Retain upstream notices and licenses whenever upstream code or assets are copied, modified or redistributed.

## NGINX

The Gauzy Hub reverse proxy uses the official NGINX Alpine container image. NGINX is distributed under the 2-clause BSD license. The proxy configuration and Floodman launcher assets in this package are separate Floodman integration code.
