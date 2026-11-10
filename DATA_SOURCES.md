# Data sources

FeedbackPulse runs on one public dataset. We don't scrape anything ourselves.

## Spotify Reviews (Google Play)

| Field | Value |
|---|---|
| Title | Spotify Reviews: Spotify Music App reviews on Google Play Store |
| Author | Ashish Kumar (Kaggle: `ashishkumarak`) |
| Repository | Kaggle, version 3 (published 2024-05-10) |
| URL | https://www.kaggle.com/datasets/ashishkumarak/spotify-reviews-playstore-daily-update |
| License | Apache 2.0, as declared by the uploader on Kaggle |
| File used | `spotify_reviews.csv` (sha256 `d1eec62d…c0e4`) |
| Download | `./scripts/download_data.sh` (pins the version and verifies the checksum) |

**Attribution:** Kumar, A. (2024). *Spotify Reviews* (Version 3) [Data set]. Kaggle.
Changes made: reviewer names dropped; text cleaned, PII-scrubbed, and filtered to English; enriched with
derived themes and release dates.

**Provenance note:** the license is the one the uploader declared, and the uploader collected the reviews
from Google Play. We can't independently confirm the uploader's rights to the review text, so this project
is for education and portfolio use only. The `userName` column is never loaded.

### Raw profile (measured in `notebooks/01_explore.ipynb`, before cleaning)
- 84,165 reviews, 1 app, Sep 2018 → May 2024
- `reviewCreatedVersion` present on 93.1% of rows
- 441 versions: 252 with 50+ reviews, 93 with 200+ reviews
- 0 duplicate review IDs, 0 empty reviews; median review 321 characters
- Average rating in this sample: 2.44

### Known limitations
- **Uneven coverage over time.** Q4 2023 onward holds 46% of the reviews, against roughly 2,000 to 3,000 per
  quarter before that. This looks like a result of how the reviews were collected, so review *volume* over
  time must not be presented as real growth.
- **It's a sample.** The average rating describes these reviews, not Spotify's overall store rating.
- **Ends in May 2024,** and covers one app.

### Why this dataset
- It has the best text of the candidates we measured (median 321 characters), which drives theme quality.
- It has a per-review app version and plenty of versions with enough reviews to compare releases.
- It fits the Supabase free tier without sampling.

### Alternatives considered (all measured)
| Dataset | License | Reviews | Median chars | Why not |
|---|---|---|---|---|
| OEM Connected-Car, Mendeley (DOI 10.17632/fsrgtm6vf7.2) | CC BY 4.0 | 24,103 | 73 | Cleanest provenance, but smaller, with shorter text and only 88 versions with 50+ reviews |
| Bumble, Kaggle | CC BY 4.0 | 184,500 | 74 | Current through Nov 2026, but shorter text and would need sampling |
| Medium, Kaggle | CC0 | 62,633 | 32 | Very short reviews |
| Twitch, Kaggle | Apache 2.0 | 97,548 | 46 | Short reviews, and two version-number lines appear mixed together |
| ChatGPT, Kaggle | CC BY-NC-SA 4.0 | 1,218,887 | 12 | Very short reviews, would need heavy sampling |
| Tinder, Kaggle | CC BY 4.0 | 680,491 | 39 | Short reviews, would need sampling |
| TikTok, Kaggle | CC0 | 307,057 | 14 | Covers only 11 weeks |
| Top 15 apps, Zenodo (10204232) | CC BY 4.0 | 15,000 | not measured | No review dates |
