# Session-expiry notice

Keep an authentication failure visible instead of replacing it with a generic
engagement-load error or clearing it as an ordinary four-second toast. A typed
client-side expiry error preserves the existing401 rejection through provider
callbacks. Backend authentication, session selection and local CSRF behavior are
unchanged. Regression cases cover concurrent401s, notice lifetime, ordinary toast
expiry and network errors; the existing browser assertion stays unchanged.
