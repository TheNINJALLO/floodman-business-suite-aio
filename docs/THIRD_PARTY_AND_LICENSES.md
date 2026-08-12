# Third-party components and licensing boundaries

This is an engineering inventory, not legal advice. Obtain a qualified review before commercial redistribution or production launch.

## Ever Gauzy

The current AIO design uses Gauzy API and web images as the ERP foundation. Gauzy is an upstream project with its own AGPL licensing obligations. Keep its notices intact and determine whether the intended hosted use, modifications, distribution and branding require source availability or a commercial agreement.

The handoff does not include a copied Gauzy repository. The Dockerfile composes upstream images.

## Documenso

Documenso is the signing engine and is likewise an upstream AGPL project. Preserve its notices and determine the obligations for hosted/network use, white-labeling, modifications and redistribution.

The handoff does not include a copied Documenso repository. The Dockerfile composes an upstream image.

## RoomFlow

RoomFlow is maintained in `TheNINJALLO/roomflow` and pinned to commit:

```text
1f97817a52b916875e50cc6380c0d284072b8ce8
```

Its source is fetched during builds. Confirm and preserve the repository's license before redistribution or incorporation into an app-store binary.

## Square, Twilio, OpenAI and Tailscale

These are service/API relationships governed by their provider terms. Credentials remain server-side. Payment, messaging, AI/privacy and network-exposure rules must be reviewed separately from open-source licensing.

## Other components

PostgreSQL, Nginx, Python, Node.js, Mailpit, Android libraries, Swift/Apple frameworks and transitive dependencies retain their respective licenses. Generate an SBOM from every final image/app and retain license notices.

## Source-offer and notices strategy

Before release:

1. Inventory every copied upstream file and image layer.
2. Preserve copyright/license files.
3. Publish or offer corresponding source where required.
4. Separate proprietary Floodman modules clearly from upstream code.
5. Place a Third-party Notices page in the product.
6. Record exact source commits and image digests.
7. Review branding statements so Floodman is not represented as endorsed by upstream projects.
