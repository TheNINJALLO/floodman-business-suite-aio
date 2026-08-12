# Pterodactyl installation

## 1. Build the image

Create a GitHub repository, place this package at the repository root, and run **Actions → Build Floodman Pterodactyl AIO → Run workflow**. The workflow publishes:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1
```

Make the GHCR package public for the simplest test deployment, or configure private-registry credentials in Wings. Do not place a GitHub token in an editable egg variable.

## 2. Create allocations

On the target Wings node, create five TCP allocations on the same node IP:

```text
9000  Main Hub, primary allocation
9001  Documenso
9002  Mailpit
9003  Engineering Sandbox
9004  Floodman API
```

## 3. Import the egg

In the Pterodactyl Admin Panel, create or select a Nest and import `egg-floodman-business-suite-aio.json`.

## 4. Create the server

Recommended test limits:

```text
Memory: 24576 MB
Swap:    4096 MB
Disk:    81920 MB
CPU:     600% minimum, 800% recommended
```

Select port `9000` as the primary allocation. Assign `9001`, `9002`, `9003`, and `9004` as additional allocations. Keep **Enforce 9000 Port Scheme** set to `true` so a mismatched allocation fails clearly instead of creating broken links.

## 5. Startup variables

Replace the placeholder Owner email and password. Leave the port variables at their defaults unless the assigned allocations differ. For direct testing, use `http` and set **Public Host** to the node IP or DNS hostname.

## 6. First boot

The first boot initializes an embedded PostgreSQL cluster, three databases, genuine Gauzy with `DEMO=false`, Documenso, and the Floodman services. Wait for the console marker:

```text
FLOODMAN_SUITE_READY
```

First startup may take 10 to 30 minutes.

## 7. Addresses

Assuming node host `example.test`:

```text
http://example.test:9000        Main Hub
http://example.test:9001        Documenso
http://example.test:9002        Mailpit
http://example.test:9003/lab    Engineering Sandbox
http://example.test:9004/docs   Floodman API Explorer
```

Use HTTPS through a reverse proxy before entering real customer information. Restrict ports 9002, 9003, and API documentation on 9004 to trusted administrators.
