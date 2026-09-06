# Fonts (self-hosted, air-gapped)

Place these files here (both are open licence, OFL):

- `Manrope-Variable.woff2` — https://github.com/sharanda/manrope (or Google Fonts download)
- `JetBrainsMono-Variable.woff2` — https://github.com/JetBrains/JetBrainsMono

`app/globals.css` declares the `@font-face` rules. If the files are missing the UI
falls back to the system sans/mono stacks and nothing is fetched from the network.
