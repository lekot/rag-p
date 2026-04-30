# Cohere selective-egress sidecar.
#
# Two processes inside one container:
#   1. amneziawg-go     — userspace AmneziaWG client (protocol_version=2 with
#                          obfuscation fields Jc/Jmin/Jmax/S1-S4/H1-H4/I1).
#                          Standard wireguard-tools cannot parse those, so we
#                          ship the AmneziaWG fork explicitly.
#   2. tinyproxy        — HTTP forward proxy on :8888. The api / worker
#                          containers point cohere SDK calls at it; everything
#                          else stays on the direct docker bridge path.
#
# The container falls back to a "tinyproxy without VPN" mode if the
# /etc/amneziawg/awg0.conf volume is missing — handy for local smoke / CI.

ARG ALPINE_VERSION=3.20
ARG GO_VERSION=1.25

# ---------------------------------------------------------------------------
# Stage 1: build amneziawg-go (userspace wireguard implementation with AWG)
# ---------------------------------------------------------------------------
FROM golang:${GO_VERSION}-alpine AS awg-go-build

ARG AWG_GO_REF=master

RUN apk add --no-cache git build-base

WORKDIR /src
RUN git clone --depth 1 --branch "${AWG_GO_REF}" \
      https://github.com/amnezia-vpn/amneziawg-go.git . \
 && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/amneziawg-go .

# ---------------------------------------------------------------------------
# Stage 2: build amneziawg-tools (awg, awg-quick — the AWG fork of wg-tools)
# ---------------------------------------------------------------------------
FROM alpine:${ALPINE_VERSION} AS awg-tools-build

ARG AWG_TOOLS_REF=master

RUN apk add --no-cache git make gcc musl-dev linux-headers bash

WORKDIR /src
RUN git clone --depth 1 --branch "${AWG_TOOLS_REF}" \
      https://github.com/amnezia-vpn/amneziawg-tools.git . \
 && cd src \
 && make \
 && make install DESTDIR=/out PREFIX=/usr \
      WITH_WGQUICK=yes WITH_BASHCOMPLETION=no WITH_SYSTEMDUNITS=no

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      iproute2 \
      iptables \
      tinyproxy \
 && update-ca-certificates

COPY --from=awg-go-build    /out/amneziawg-go        /usr/local/bin/amneziawg-go
COPY --from=awg-tools-build /out/usr/bin/awg         /usr/bin/awg
COPY --from=awg-tools-build /out/usr/bin/awg-quick   /usr/bin/awg-quick

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY entrypoint.sh  /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8888

# awg-quick expects the userspace implementation under WG_QUICK_USERSPACE_IMPLEMENTATION
ENV WG_QUICK_USERSPACE_IMPLEMENTATION=amneziawg-go \
    WG_SUDO=1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
