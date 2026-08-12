# AIO image builds

`Dockerfile` is the current source-oriented all-in-one build. `Dockerfile.legacy-v3.1.1` is retained as provenance for the first working Pterodactyl AIO design.

The image intentionally composes upstream application images rather than copying their repositories into this handoff. Before production or redistribution:

- pin every upstream image to an immutable digest;
- review Gauzy and Documenso AGPL obligations;
- retain notices and source-offer obligations where applicable;
- scan the final image for vulnerabilities and secrets;
- build and test from a clean runner.

For the least disruptive migration, build `containers/derivative/Dockerfile` first. It places the current Floodman source on the already-used AIO base image.
