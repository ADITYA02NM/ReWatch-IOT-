#!/usr/bin/env bash
set -euo pipefail
#
# Offline root CA + server certificate for rewatch.local
#
# Usage:
#   ./tools/make_local_ca.sh              # creates ca/ and certs/ under repo root
#   ./tools/make_local_ca.sh --reissue    # reissue server cert from existing CA
#
# Output layout:
#   ca/ca.key       Root CA private key (NEVER goes on Pi or into git)
#   ca/ca.crt       Root CA certificate (install on owner devices)
#   certs/server.key   Server private key (deploy to Pi, mode 0600)
#   certs/server.crt   Server certificate (deploy to Pi)
#
# All keys are EC P-256. Server cert validity <= 825 days.
# ca.key lives on the admin SSD only.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CA_DIR="$REPO_ROOT/ca"
CERT_DIR="$REPO_ROOT/certs"
DAYS_CA=3650
DAYS_SERVER=825
DOMAIN="rewatch.local"

reissue=false
if [[ "${1:-}" == "--reissue" ]]; then
    reissue=true
fi

mkdir -p "$CA_DIR" "$CERT_DIR"

# ── Root CA ──────────────────────────────────────────────────────────────────
if [[ "$reissue" == false ]]; then
    if [[ -f "$CA_DIR/ca.key" ]]; then
        echo "ERROR: $CA_DIR/ca.key already exists. Use --reissue to issue a new server cert."
        exit 1
    fi

    echo "── Generating root CA (EC P-256) ──"
    openssl ecparam -genkey -name prime256v1 -noout -out "$CA_DIR/ca.key"
    chmod 600 "$CA_DIR/ca.key"

    # Use a temp config to avoid Git Bash MSYS path mangling on -subj
    _ca_cnf="$CA_DIR/_ca_req.cnf"
    cat > "$_ca_cnf" <<'CACNF'
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ReWatch Local CA
O  = ReWatch
OU = Governance
CACNF

    openssl req -new -x509 -key "$CA_DIR/ca.key" \
        -config "$_ca_cnf" \
        -out "$CA_DIR/ca.crt" \
        -days "$DAYS_CA" \
        -sha256
    rm -f "$_ca_cnf"

    echo "  CA certificate: $CA_DIR/ca.crt"
    echo "  CA private key: $CA_DIR/ca.key  (NEVER put this on the Pi or in git)"
else
    if [[ ! -f "$CA_DIR/ca.key" || ! -f "$CA_DIR/ca.crt" ]]; then
        echo "ERROR: CA files not found. Run without --reissue first."
        exit 1
    fi
    echo "── Reissuing server certificate from existing CA ──"
fi

# ── Server certificate ───────────────────────────────────────────────────────
echo "── Generating server certificate for $DOMAIN (EC P-256, ${DAYS_SERVER}d) ──"

openssl ecparam -genkey -name prime256v1 -noout -out "$CERT_DIR/server.key"
chmod 600 "$CERT_DIR/server.key"

_srv_cnf="$CERT_DIR/_srv_req.cnf"
cat > "$_srv_cnf" <<SRVCNF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = $DOMAIN
O  = ReWatch
SRVCNF

openssl req -new -key "$CERT_DIR/server.key" \
    -config "$_srv_cnf" \
    -out "$CERT_DIR/server.csr" \
    -sha256
rm -f "$_srv_cnf"

_ext_cnf="$CERT_DIR/_server_ext.cnf"
cat > "$_ext_cnf" <<EXTCNF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$DOMAIN
EXTCNF

openssl x509 -req -in "$CERT_DIR/server.csr" \
    -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -days "$DAYS_SERVER" \
    -sha256 \
    -extfile "$_ext_cnf"

rm -f "$CERT_DIR/server.csr" "$_ext_cnf" "$CA_DIR/ca.srl"

echo ""
echo "── Done ──"
echo "  Server cert : $CERT_DIR/server.crt"
echo "  Server key  : $CERT_DIR/server.key"
echo ""
echo "── CA fingerprint (SHA-256) ──"
openssl x509 -in "$CA_DIR/ca.crt" -noout -fingerprint -sha256
echo ""
echo "Install ca/ca.crt on owner devices (see use.md for per-platform steps)."
echo "Deploy certs/server.crt and certs/server.key to the Pi4."
echo "NEVER deploy ca/ca.key — it stays on the admin SSD."
