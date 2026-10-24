# HireSense AI frontend

React + TypeScript + Vite + Tailwind CSS. The API types in `src/api/schema.d.ts` are generated from the
backend's OpenAPI spec, so the TypeScript compiler catches any mismatch between frontend and backend.

    npm install
    npm run dev          # http://localhost:5173  (forwards /api and /ws to http://localhost:8000)
    npm test             # component and logic tests (no backend needed)
    npm run build        # type-check + production build into dist/

To refresh the generated API types after changing the backend (backend running on port 8000):

    npm run gen:types
