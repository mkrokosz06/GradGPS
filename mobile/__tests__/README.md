# Mobile tests

No test runner is configured yet. Setup when we start:

```bash
npx expo install jest-expo jest @testing-library/react-native --dev
# package.json: "test": "jest", "jest": { "preset": "jest-expo" }
```

Jest auto-discovers `__tests__/` and `*.test.ts(x)` files.

## Ideas

- **Service logic (cheapest wins first)** — `transcriptService.isOfficialAckError()`
  against real 409/other error shapes; axios interceptor attaches Bearer token;
  error handlers never render `[object Object]`.
- **AuthContext** — dev fallback to hardcoded USER_ID when storage empty; token
  stored/cleared on sign-in/out; 401 from API signs the user out (once refresh
  handling exists).
- **TosModal gate** — signup cannot proceed without agreeing; agree fires callback.
- **Upload consent flow** — mock a 409 `needs_official_ack` response, assert the
  Alert shows and re-upload is sent with `acknowledge_official=true`.
- **NavHeader** — every menu item navigates to a route that exists (guards against
  renamed routes breaking the hamburger menu silently).
- **Timeline rendering** — given a mock `/timeline` payload: semesters render in
  order, pool placeholders show the dropdown affordance, credit totals match.
