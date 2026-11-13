# Releasing mods

```
python "${CLAUDE_SKILL_DIR}/scripts/release.py" "<mod folder>" ["<mod folder>" ...] --version 1.2.0 [--note "Added the Cottage"]... [--out releases] [--dry-run] [--allow-placeholders]
```
Run from the project root (the folder with `sdv-project.json`, or the mods' parent). It prepares a release and **never uploads or publishes anything**.

What it does, in order (nothing is written if a step fails):
1. **Validates** every mod with `validate_mod.py`; any ERROR stops the release. Leftover placeholder art stops it too (`--allow-placeholders` for a deliberate preview build).
2. **Versions**: sets `Version` in each `manifest.json` (a text edit, nothing else in the file changes) and, where one of the mods lists another of the same release in `Dependencies`, raises that dependency's `MinimumVersion` to the new version.
3. **Changelog**: prepends a section to `CHANGELOG.md` with your `--note` lines plus what changed since the last release (new custom IDs and assets installed since then, from `sdv-project.json`), then records this release in the project file.
4. **Zips** into `releases/` (outside the mods): one zip per mod (`<Name> <version>.zip`, top folder = the mod folder) and one all-in-one zip. C# mods are built in Release first and packaged from the build output. Left out: `config.json` (generated per player), `backups/`, `runs/`, `art-source/`, `*_preview.png`, `*.bak`, `* - Copy*`, `bin/obj` of content packs, `.git`, `Thumbs.db`, `.DS_Store`.
5. **Draft text**: `releases/<Project> <version> - description.md` built from the manifests' descriptions, requirements (dependencies) and the changelog section. It is a draft for the owner to paste.

`UpdateKeys` are only set when the owner supplies real Nexus/GitHub IDs (`--update-key Nexus:1234`, written to each manifest); otherwise they stay as they are.
After a release, tell the owner where the zips are and that nothing was uploaded. Testing the zip in a clean mods folder (`game.py test` against the unzipped folder) is the last check before they publish.
