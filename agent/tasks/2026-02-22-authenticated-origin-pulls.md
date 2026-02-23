---
status: done
refs:
  - "[[2026-02-21-endpoint-rate-limiting]]"
  - "[[security]]"
  - "[[vps-setup]]"
---

# Authenticated Origin Pulls (mTLS) with custom certificate

## Intent

Rate limiting requires a trustworthy client IP. The real IP comes from Cloudflare's `CF-Connecting-IP` header, which is only trustworthy if all traffic goes through Cloudflare. Without mTLS, someone who discovers the origin IP (46.224.195.97) can connect directly and send fake headers.

AOP adds mutual TLS: Cloudflare presents a client certificate when connecting to Traefik. Traefik verifies the cert is signed by our private CA. Connections without the cert (direct-to-origin) are rejected at the TLS layer.

Using a custom certificate (not Cloudflare's shared one) so only our Cloudflare zone can connect — not other Cloudflare customers.

## Steps

### 1. Generate certs locally

```bash
# Private CA (10 years)
openssl genrsa -aes256 -out aop-ca.key 4096
openssl req -x509 -new -nodes -key aop-ca.key -sha256 -days 3650 -out aop-ca.crt \
  -subj "/C=US/O=Yapit/CN=yapit.md"

# Client cert signed by CA (10 years)
openssl req -new -nodes -out aop-client.csr -newkey rsa:4096 -keyout aop-client.key \
  -subj "/C=US/O=Yapit/CN=yapit.md"
echo "basicConstraints=CA:FALSE" > aop-client.v3.ext
openssl x509 -req -in aop-client.csr -CA aop-ca.crt -CAkey aop-ca.key \
  -CAcreateserial -out aop-client.crt -days 3650 -sha256 -extfile aop-client.v3.ext
```

Store `aop-ca.key` passphrase securely. The CA key is only needed to issue new client certs (renewal in ~10 years).

### 2. Upload client cert to Cloudflare (API only)

Need: Zone ID (`e307c22342c2d1dada1d4d45da3e1bce`) + API token with **Account**-level "SSL and Certificates Edit" AND **Zone**-level "Zone Read" permissions. Zone-level SSL alone won't work for this endpoint.

```bash
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/origin_tls_client_auth" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data "$(jq -n \
    --arg cert "$(cat aop-client.crt)" \
    --arg key "$(cat aop-client.key)" \
    '{certificate: $cert, private_key: $key}')"
```

Check status (must be `active` before proceeding):
```bash
curl -s "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/origin_tls_client_auth" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq '.result[] | {id, status, expires_on}'
```

### 3. Deploy CA cert to VPS

```bash
scp aop-ca.crt root@46.224.195.97:/opt/yapit/traefik/certs/aop-ca.crt
```

### 4. Configure Traefik — permissive first

Edit `/opt/yapit/traefik/dynamic/certs.yml` on the VPS, add:

```yaml
  options:
    default:
      clientAuth:
        caFiles:
          - /etc/traefik/certs/aop-ca.crt
        clientAuthType: VerifyClientCertIfGiven
```

Restart Traefik: `docker restart traefik`

Verify site works normally through Cloudflare.

### 5. Enable AOP in Cloudflare

Dashboard: SSL/TLS → Origin Server → Authenticated Origin Pulls → On

Or API:
```bash
curl -X PUT "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/origin_tls_client_auth/settings" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"enabled": true}'
```

Verify site still works through Cloudflare.

### 6. Switch Traefik to strict mode

Change `clientAuthType` from `VerifyClientCertIfGiven` to `RequireAndVerifyClientCert`.

Restart Traefik: `docker restart traefik`

### 7. Verify

- `https://yapit.md` through browser → works
- `curl --resolve yapit.md:443:46.224.195.97 https://yapit.md/ -k` → TLS handshake fails (no client cert)

## Notes

- Cloudflare cert ID: `665c1769-5945-43ac-8fdd-8324b00411cc`, expires 2036-02-20.
- The `default` TLS option name is special in Traefik — applies to all routers automatically. No docker-compose label changes needed.
- TLS options must be in the file provider (dynamic config), not Docker labels — Traefik limitation.
- SSH (port 22), Redis via Tailscale (port 6379) are unaffected.
- The permissive → strict two-phase rollout avoids downtime if something is misconfigured.

## Done when

- Direct-to-origin HTTPS connections rejected (TLS handshake fails without client cert)
- Site works normally through Cloudflare
- CA key stored securely, cert expiry noted (2036)
