# JavaScript unit tests

`frontend_statistics.test.mjs` executes the current production functions from `app/web/compare-builder.js` rather than testing a copied implementation. Until the pure logic is physically extracted into its own module, the test locates top-level function declarations by name and evaluates them in a Node VM.

This is intentionally a transition seam: it gives numerical regression protection before the large `compare-builder.js` refactor. Once the pure functions move to a standalone module, the test should import that module directly and this extraction helper should be deleted.
