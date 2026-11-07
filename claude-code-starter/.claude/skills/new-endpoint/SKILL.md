---
name: new-endpoint
description: Adds a new REST API endpoint. Use when the user asks to add, create or expose a new API route.
---

<!-- Example skill. Replace the paths and steps with your own team's procedure. -->

1. Create the route in `src/api/<resource>.ts`, following the pattern in an existing route file
2. Add request and response types to `src/types/api.ts`
3. Validate input (for example with zod). Never trust request bodies.
4. Write tests in `tests/api/<resource>.test.ts` covering success, bad input, and not found
5. Run the tests and fix failures before reporting done
