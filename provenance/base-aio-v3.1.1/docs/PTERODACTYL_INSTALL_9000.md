# Install Floodman AIO in Pterodactyl using ports 9000-9004

## 1. Create node allocations

In the Pterodactyl Admin Panel:

```text
Nodes → your Wings node → Allocations
```

Add TCP allocations for:

```text
9000
9001
9002
9003
9004
```

Use the real Wings-node interface IP shown by the panel. Do not use `127.0.0.1` as the allocation IP.

## 2. Build and publish the image

Follow `BUILD_AND_PUBLISH_IMAGE.md`. Confirm this image is pullable by Wings:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1
```

## 3. Import the egg

In the Pterodactyl Admin Panel:

```text
Nests → Import Egg
```

Import:

```text
egg-floodman-business-suite-aio.json
```

Create or select a Nest such as **Floodman Business Applications**.

## 4. Create the server

Recommended testing limits:

```text
Memory: 24576 MB
Swap: 4096 MB
Disk: 81920 MB
CPU: 600% minimum, 800% preferred
OOM killer: enabled for testing
```

Assign:

```text
Primary allocation: 9000
Additional allocation: 9001
Additional allocation: 9002
Additional allocation: 9003
Additional allocation: 9004
```

## 5. Configure Startup variables

Set real values for:

```text
Company Name
Owner First Name
Owner Last Name
Owner Email
Owner Password
Time Zone
Public Host
Public Scheme
```

Keep these port values:

```text
Enforce 9000 Port Scheme = true
Documenso Port = 9001
Mailpit Port = 9002
Engineering Sandbox Port = 9003
Floodman API Port = 9004
```

For direct IP testing:

```text
Public Scheme = http
Public Host = YOUR_NODE_IP_OR_DNS
```

Do not include `http://`, `https://`, or a port in **Public Host**.

## 6. Start the server

The first start initializes one embedded PostgreSQL cluster, creates three databases, starts genuine Gauzy in non-demo mode, configures the Floodman Owner, starts Documenso, and starts the Floodman services.

Expected final console marker:

```text
FLOODMAN_SUITE_READY
```

First startup can take 10-30 minutes on a lightly loaded node and longer on shared hardware.

## 7. Open the services

Replace `HOST` with the node IP or DNS name:

```text
Main Hub:            http://HOST:9000
Documenso:           http://HOST:9001
Mailpit:             http://HOST:9002
Engineering Sandbox http://HOST:9003/lab
Floodman API:        http://HOST:9004/docs
```

## 8. Security for testing

Ports `9002`, `9003`, and `9004` expose administrative/testing surfaces. Restrict them with a VPN, source-IP firewall rules, or an authenticated reverse proxy. Do not expose PostgreSQL or the internal AI ports.

## 9. Backups

All persistent AIO data lives under `/home/container`. For the most consistent test backup:

1. Stop the Pterodactyl server.
2. Create a Pterodactyl backup.
3. Wait for completion.
4. Restart the server.
