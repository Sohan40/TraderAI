# Nginx and HTTPS

Nginx is not deployed in P02.

Before any public dashboard, login route, broker callback, or operator control surface is exposed, add and review:

- HTTPS certificates.
- Authentication and authorization.
- Request logging with secret redaction.
- Restricted firewall rules.
- Reverse-proxy headers reviewed for FastAPI.
- A rollback path that keeps `TRADING_MODE=OFF` and `LIVE_ARMED=false`.

Until then, use the API only through VM-local health checks or an SSH tunnel.
