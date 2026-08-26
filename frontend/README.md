# CloudWard frontend

The CloudWard operations dashboard is a React and TypeScript single-page
application. It talks to the versioned control-plane REST API through the
same-origin `/api/v1` path by default; Nginx provides that route in the local
Compose environment.

```bash
npm ci
npm run dev
npm test
npm run lint
npm run build
```

Set `VITE_API_BASE_URL` only when the API is served from a different origin.
The dashboard treats failed dependency checks as unavailable; it never invents
healthy operational data when the API cannot be reached.
