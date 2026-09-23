@../CLAUDE.md

# Mobile-specific notes

- Expo SDK 54 / Expo Router v6. Read versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.
- The `(tabs)` layout MUST stay as `<Tabs>` (not Stack) even though the tab bar is hidden. Changing it to Stack breaks `router.navigate()` between sibling screens.
- NativeWind v4 — use `className` props, not `style` objects, for Tailwind classes. Custom colors are defined in `tailwind.config.js`.
- `assets/icon.png` must stay **opaque RGB** (no alpha) — Apple requires the 1024 marketing icon to
  have none; don't rely on the build to flatten it. The Android adaptive-icon layers keep their alpha.
  App Store screenshots have the same no-alpha rule.
