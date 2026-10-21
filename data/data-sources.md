# Data sources

## Glottolog (language list)
- Used for: `core.languages` (ISO 639-3 code, name, family), filtered to languages with country code PH.
- Source: Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian. 2026. Glottolog 5.3. Leipzig: Max Planck Institute for Evolutionary Anthropology. https://glottolog.org
- Distribution used: CLDF dataset, https://github.com/glottolog/glottolog-cldf (languages.csv)
- License: CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/). Attribution required.
- Country assignment is Glottolog's own and differs from other catalogues (e.g. Ethnologue).
- Re-running the seed overwrites name, family and notes with Glottolog's values.