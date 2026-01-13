# Observability Troubleshooting Notes

## Issue: Grafana "Services" and "Container Resources" panels show no data

### Symptoms
- Prometheus target `cadvisor` is up, but Grafana panels for container stats are blank.
- Prometheus series for cAdvisor metrics only include labels like `id`, `instance`, `job`.
- `http://localhost:8081/metrics` shows only root-level samples (no per-container series).
- `brain-cadvisor` logs include errors like:
  - `Failed to create existing container ... open /rootfs/var/lib/docker/image/overlayfs/.../mount-id: no such file or directory`

### Cause
On Docker Desktop/macOS, cAdvisor cannot access the Docker Engine layerdb
at `/var/lib/docker`. This prevents cAdvisor from building per-container stats
and labels (including Docker Compose labels), so Prometheus only sees host
root entries. The Grafana panels in the Infrastructure dashboard depend on
per-container metrics and labels.

### Recommended next steps
1) Verify cAdvisor scrape is up:
   - `http://localhost:9090/targets` (job `cadvisor` should be `UP`).
2) Check whether per-container labels exist:
   - `curl -sS 'http://localhost:9090/api/v1/series?match[]=container_memory_usage_bytes'`
   - If labels are only `__name__,id,instance,job`, cAdvisor is not emitting
     container metrics.
3) Inspect cAdvisor logs for layerdb errors:
   - `docker logs --tail 50 brain-cadvisor`
4) If on Docker Desktop/macOS:
   - This is expected; cAdvisor cannot read `/var/lib/docker` inside the VM.
   - Recommended fix is to run the observability stack on a Linux host/VM
     with direct access to Docker storage.
5) Optional experiment (may not fix labels):
   - Try a different cAdvisor image/tag or configuration that uses the
     Docker API and cgroups without relying on layerdb, but results vary
     on Docker Desktop.

