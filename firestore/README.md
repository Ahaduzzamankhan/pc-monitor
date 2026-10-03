# Firestore setup

PC Monitor stores everything in Google Cloud Firestore (any Firebase project
works). Only the backend uses the Firebase Admin SDK.

## Collections

```
devices/{deviceId}
  deviceId, name, agentVersion, os, architecture, hostname
  cpuModel, gpuModel, ramTotalMB, diskTotalGB
  createdAt, updatedAt, lastSeen, online
  telemetryIntervalSeconds, startupEnabled, telemetryCount
  tokenHash, tokenFingerprint          # HMAC-SHA256 only - never the raw token

devices/{deviceId}/telemetry/{autoId}
  deviceId, timestamp, expiresAt, receivedAt
  cpuUsage, cpuPerCore, cpuFrequencyMHz, cpuTemperature
  gpuUsage, gpuTemperature, vramUsedMB, vramTotalMB
  ramUsage, ramUsedMB, ramTotalMB, ramAvailableMB
  diskUsage, diskTotalGB, diskUsedGB, diskFreeGB, diskReadMbps, diskWriteMbps
  downloadMbps, uploadMbps, apiLatencyMs
  batteryPercent, batteryCharging, batteryTimeLeftSeconds
  uptimeSeconds

devices/{deviceId}/logs/{autoId}
  deviceId, event, level, message, data, timestamp

revoked_devices/{deviceId}
  deviceId, reason, revokedAt
```

## TTL policy (automatic 7-day telemetry deletion)

Every telemetry document carries `expiresAt = timestamp + TELEMETRY_RETENTION_DAYS`
(7 days by default, hard maximum 7). Firestore deletes expired documents for you:

* **Console** - Firestore Database ▸ Settings ▸ *Time-to-live* ▸ add a TTL policy
  on field `expiresAt` with state **CREATED**.
* **gcloud**

  ```bash
  gcloud firestore fields ttls update expiresAt \
    --collection-group=telemetry \
    --project=YOUR_PROJECT_ID \
    --enable-ttl
  ```

The backend also attempts this automatically at startup (see
`FirestoreStore.ensure_ttl_policy`). If TTL is unavailable for any reason, the
scheduled cleanup service (`CLEANUP_INTERVAL_MINUTES`) deletes expired telemetry
in batches with pagination. Device documents are **never** deleted automatically.

## Rules and indexes

```bash
firebase deploy --only firestore:rules,firestore:indexes --project YOUR_PROJECT_ID
```

`rules` deny every direct client read/write: only the Admin SDK (server side) can
touch the database.