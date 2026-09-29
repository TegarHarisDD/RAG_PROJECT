import '@testing-library/jest-dom/vitest'

// jsdom does not implement matchMedia; the dark-mode toggle only reads the
// OS preference from it, so a fixed light default is fine for tests.
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList
