"""Sphinx configuration for the GV Tools reference manual."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

project = "GV Tools"
author = "NASA GPM Ground Validation"
release = "0.31.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]
autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "pydata_sphinx_theme"
html_title = f"GV Tools {release} documentation"
html_static_path = ["_static"]
html_css_files = ["gv_tools.css"]
html_theme_options = {
    "navigation_with_keys": True,
    "show_toc_level": 2,
    "navbar_align": "left",
    "header_links_before_dropdown": 5,
    "secondary_sidebar_items": ["page-toc", "edit-this-page", "sourcelink"],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version", "theme-version"],
}
html_sidebars = {"**": ["search-field", "sidebar-nav-bs"]}
