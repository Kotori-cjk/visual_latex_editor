# Local application scope

This application is a single-user local editor. It binds to 127.0.0.1, validates the request host/origin, and protects writes with a session token and document revision. Do not expose the server through a public reverse proxy or a shared network.

Tectonic is invoked with `--untrusted`. This is not a complete sandbox for hostile documents. Import documents you trust, and use a separate OS/container environment if you need to handle untrusted TeX.

The server can write its configured project directory and retains prior builds there. Tectonic may download packages and fonts during compilation. No document content is sent to an application cloud service by this editor.

For a vulnerability, use GitHub's private vulnerability reporting when available. Do not include private documents or credentials in a public issue.
