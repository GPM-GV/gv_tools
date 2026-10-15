# GV Tools project instructions

- Treat `/Users/dwolff/Desktop/Work/GV_Tools` as the workspace for every task in this project.
- The package source and release workspace is `/Users/dwolff/Desktop/Work/GV_Tools/gv_tools`.
- Build fresh release artifacts into `/Users/dwolff/Desktop/Work/GV_Tools/gv_tools/dist`.
- For every new version, update `docs/conf.py`, rebuild the complete Sphinx HTML
  manual in `docs/_build/html`, verify the generated title contains the new
  version, and include the rebuilt HTML in the source archive.
- Before delivering a release, remove older wheel and source-archive versions from `dist` so it contains only the current version.
- Do not use `/Users/dwolff/Documents/ChatGPT/GV Tools` as the working source tree.
- Keep notebooks below `gv_tools/notebooks`, examples below `gv_tools/examples`, and generated HTML below `gv_tools/HTML`.
- Do not recreate the removed `release`, `piers_gauge_tools`, or `process_piers_plus` trees.
