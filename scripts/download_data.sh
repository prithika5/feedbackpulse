#!/usr/bin/env bash
# Downloads the raw dataset (Apache 2.0) into data/raw/ and verifies its checksum.
# The Kaggle version is pinned so anyone cloning the repo gets byte-identical input.
# Raw data is gitignored.
set -euo pipefail
DEST="data/raw/spotify_reviews"
URL="https://www.kaggle.com/api/v1/datasets/download/ashishkumarak/spotify-reviews-playstore-daily-update?datasetVersionNumber=3"
mkdir -p "$DEST"
curl -sSL -o "$DEST/spotify_reviews.zip" "$URL"
unzip -qo "$DEST/spotify_reviews.zip" -d "$DEST"
rm "$DEST/spotify_reviews.zip"
echo "d1eec62d27c257cb36a5f7503f5ef077960c8a1f0f7bc3cebdbc94716803c0e4  $DEST/spotify_reviews.csv" | shasum -a 256 -c -
