# Third-party and source boundaries

## Included source

This archive includes the complete Floodman-authored custom server overlay, Android application, iOS application, AIO integration source, launchers, tests, and deployment scaffolding available in the session.

## RoomFlow

RoomFlow is maintained in a separate repository and pinned by commit. Fetch scripts are provided. Its license and repository history should remain attached to that source.

## Gauzy and Documenso

The AIO image composes Gauzy and Documenso runtime images. Their repositories are not copied into this handoff. Before distributing a source-built image, review their current licenses, notices, modification/source obligations, and network-use terms with counsel. Keep visible third-party notices where required, even while the customer-facing UI is fully Floodman branded.

## Mailpit, Square, Twilio, Apple, and Google

These are external runtimes or services. Their SDKs, APIs, account terms, and distribution rules remain separate from Floodman source ownership.

## Mutable tags

The current full-image Dockerfile still uses some mutable `latest` tags. Production builds must replace them with immutable digests and record those digests in `vendor/UPSTREAMS.lock.json`.

## Meaning of full source in this handoff

“Full source” means the full custom Floodman source and all build/deployment material created in the session. It does not mean copies of every upstream open-source repository, proprietary payment processor, hosted service, or live customer dataset.
