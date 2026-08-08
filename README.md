# Stream Unifi camera to Prusa Connect

This is a simple docker bridge to stream RTSPS video to Prusa Connect. I built this because I repurposed an old Unifi G3 bullet camera to fit into my Prusa Core One. The camera is pretty big as is so I made a [custom housing](https://www.printables.com/model/1800520-unifi-g3-printer-camera) to slim it down a bit. This bridge should work with any camera that supports RTSPS.


### Install Docker
I am using a Raspberry Pi 4 (Debian 13) as my server.

```sh
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Add Docker's repository:

```sh
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/debian' \
  'Suites: trixie' \
  'Components: stable' \
  'Signed-By: /etc/apt/keyrings/docker.asc' \
  | sudo tee /etc/apt/sources.list.d/docker.sources
```

Install and enable Docker:

```sh
sudo apt update
sudo apt install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and reconnect so the Docker group membership takes effect, then verify:

```sh
docker --version
docker compose version
```

### Bridge installation

Clone this repo to your server that will act as the bridge.

```sh
git clone https://github.com/bciuca/prusa-unifi-cam.git
cd prusa-unifi-cam
```

### Configure credentials

1. In Prusa Connect, open the printer, choose **Camera**, add an **Other camera**, and copy its camera token.
2. In UniFi Protect, enable/copy the existing RTSPS link for the Protect camera.
3. On the Docker host, create the secret files (the directory is ignored by Git so you'll need to create it).

   ```sh
   cd ~/prusa-unifi-cam
   install -d -m 700 secrets
   "${EDITOR:-vi}" secrets/stream_url
   "${EDITOR:-vi}" secrets/prusa_token
   sudo chown "$USER":10001 secrets/stream_url secrets/prusa_token
   chmod 640 secrets/stream_url secrets/prusa_token
   ```

   Each file must contain only its value on one line. Numeric group `10001` is
   the non-root group used inside the container.

### Build and start

Set your port, 8080 is the default.

```sh
printf '%s\n' 'HEALTH_PORT=8080' > .env
```

Build and start the service. This may take several minutes for the first build depending on your machine.

```sh
cd ~/prusa-unifi-cam
docker compose up -d --build
```

Verify after the build has returned to the shell prompt:

```sh
docker compose ps
docker compose logs --since=1m
curl --fail http://127.0.0.1:YOUR_HEALTH_PORT/healthz
curl http://127.0.0.1:YOUR_HEALTH_PORT/readyz
```

The expected readiness response is:

```json
{"ready":true,"last_error":null,"consecutive_failures":0,"total_failures":0}
```

The image builds for AMD64 and ARM64 wherever the corresponding `python:3.13-slim-bookworm` image is available.

### Rename the camera in Prusa Connect

If the Prusa Connect website does not allow the camera name to be edited, use
the Camera API directly.

The token is on Prusa Connect in your camera tab and you can get the camera fingerprint with:
```sh
docker compose exec bridge cat /data/fingerprint
```


```sh
curl -X PUT "https://webcam.connect.prusa3d.com/c/info" \
  -H "accept: */*" \
  -H "content-type: application/json" \
  -H "fingerprint: YOUR_CAMERA_FINGERPRINT" \
  -H "token: YOUR_CAMERA_TOKEN" \
  -d '{"config": {"name": "NEW_CAMERA_NAME"}}'
```

## Stream compatibility check

Run this on the Docker host.

```sh
ffmpeg -hide_banner -loglevel error -rtsp_transport tcp -i 'rtsps://REDACTED' -frames:v 1 -f null - 2>/dev/null
```

## Operation and acceptance

After `/readyz` reports `"ready":true`, confirm the UniFi Protect camera image updates in Prusa Connect about every 10 seconds. Successful logs should appear at the same cadence. `docker compose stop` immediately stops new captures/uploads and does not alter either endpoint. Logs contain only categories such as `stream capture failed`, `Prusa authentication failed`, or `Prusa rate limit reached`. No URLs, credentials, headers, tokens, and image data are logged.

The health port is published only on host loopback. The container runs as UID 10001 with a read-only root, no Linux capabilities, no-new-privileges, bounded CPU/memory/PIDs, and a small in-memory `/tmp`. Secrets are read-only Compose mounts and excluded from the build context. The snapshot itself remains in process memory.

For added peace of mind, you can restrict the server bridge via your firewall so it can reach only the configured camera stream and Prusa HTTPS endpoint.

## Tests

```sh
python -m unittest discover -s tests -v
docker compose config
```

Automated tests use only local fakes and loopback listeners. The tests do not probe the network or use the configured camera.

## Routine service commands

Run from the project directory on the Docker host:

```sh
docker compose up -d
docker compose stop
docker compose restart
docker compose ps
docker compose logs --since=1m
```

After copying updated source files to the Pi, rebuild with:

```sh
docker compose up -d --build
```
