# Profile art. `make` regenerates everything that does not need a photo.
PY ?= python3
COLS ?= 92
# Tuned for the committed photo. Lower STRENGTH if large dark areas wash out;
# lower WHITE_POINT to pull more midtone detail into the face.
STRENGTH ?= 0.45
WHITE_POINT ?= 0.96

.PHONY: all art stats stats-offline card portrait placeholder preview test validate clean

all: art

## Everything the daily workflow keeps fresh, plus the static card.
art: stats card

## Fetch stats, then draw the heatmap and the three supporting graphics.
stats:
	$(PY) scripts/fetch_stats.py
	$(PY) scripts/render_heatmap_svg.py
	$(PY) scripts/render_cards_svg.py

## Re-draw from the data already in data/stats.json, without refetching.
stats-offline:
	$(PY) scripts/render_heatmap_svg.py
	$(PY) scripts/render_cards_svg.py

## Parser selftest + SVG checks. No network.
test:
	$(PY) scripts/fetch_stats.py --selftest
	$(PY) scripts/validate_svgs.py

validate:
	$(PY) scripts/validate_svgs.py

card:
	$(PY) scripts/make_info_card.py

## Needs source-photo.jpg in the repo root and requirements-portrait.txt.
portrait:
	$(PY) scripts/prep_photo.py source-photo.jpg --strength $(STRENGTH)
	$(PY) scripts/make_ascii_svg.py --cols $(COLS) --white-point $(WHITE_POINT)

## Stand-in portrait, used only until a real photo is added.
placeholder:
	$(PY) scripts/make_placeholder_photo.py
	$(PY) scripts/make_ascii_svg.py --cols $(COLS)

## Frozen frames + an HTML page, for looking at the layout locally.
preview:
	@mkdir -p .preview
	STATIC=1 $(PY) scripts/make_ascii_svg.py --cols $(COLS) -o .preview/ascii.svg
	STATIC=1 $(PY) scripts/make_info_card.py -o .preview/card.svg
	STATIC=1 $(PY) scripts/render_heatmap_svg.py -o .preview/heatmap.svg
	STATIC=1 $(PY) scripts/render_cards_svg.py --out-dir .preview
	@printf '%s\n' \
	  '<!doctype html><meta charset="utf-8">' \
	  '<style>body{margin:0;padding:20px;background:#fff;font:14px system-ui}' \
	  'td{vertical-align:top;padding:0 6px}</style>' \
	  '<img src="heatmap.svg" width="860"><br><br>' \
	  '<table><tr><td><img src="ascii.svg" width="370"></td>' \
	  '<td><img src="card.svg" width="490"></td></tr></table><br>' \
	  '<table><tr><td><img src="streak.svg" width="425"></td>' \
	  '<td><img src="langs.svg" width="425"></td></tr></table><br>' \
	  '<img src="year.svg" width="860">' \
	  > .preview/index.html
	@echo "open .preview/index.html"

clean:
	rm -rf .preview source-prepped.png
