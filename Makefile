.PHONY: readme-graphics

# Rebuild the profile graphics in assets/ from scripts/readme/build_profile_graphics.py.
readme-graphics:
	uv run scripts/readme/build_profile_graphics.py
